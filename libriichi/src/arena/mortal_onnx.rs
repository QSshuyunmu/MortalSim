use std::path::PathBuf;
use std::sync::Mutex;

use ort::ep;
use ort::session::Session;
use ort::value::TensorRef;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

pub(crate) struct NativeBatch {
    pub actions: Vec<usize>,
    pub q_values: Vec<Vec<f32>>,
}

#[pyclass]
pub struct MortalOnnxEngine {
    session: Mutex<Session>,
    version: u32,
    enable_rule_based_agari_guard: bool,
}

#[pymethods]
impl MortalOnnxEngine {
    #[new]
    #[pyo3(signature = (model_path, device_id = 0, enable_rule_based_agari_guard = true))]
    fn new(
        model_path: PathBuf,
        device_id: i32,
        enable_rule_based_agari_guard: bool,
    ) -> PyResult<Self> {
        if !model_path.is_file() {
            return Err(PyValueError::new_err(format!(
                "ONNX model does not exist: {}",
                model_path.display()
            )));
        }
        let cuda = ep::CUDA::default()
            .with_device_id(device_id)
            .build()
            .error_on_failure();
        let builder = Session::builder()
            .map_err(|err| PyRuntimeError::new_err(format!("create ONNX session: {err}")))?;
        let mut builder = builder.with_execution_providers([cuda]).map_err(|err| {
            PyRuntimeError::new_err(format!("register ONNX CUDA provider: {err}"))
        })?;
        let session = builder
            .commit_from_file(&model_path)
            .map_err(|err| PyRuntimeError::new_err(format!("load ONNX model: {err}")))?;
        Ok(Self {
            session: Mutex::new(session),
            version: 4,
            enable_rule_based_agari_guard,
        })
    }

    #[getter]
    fn version(&self) -> u32 {
        self.version
    }

    #[getter]
    fn enable_rule_based_agari_guard(&self) -> bool {
        self.enable_rule_based_agari_guard
    }
}

impl MortalOnnxEngine {
    pub(crate) fn infer(
        &self,
        obs: &[f32],
        masks: &[[bool; crate::consts::ACTION_SPACE]],
        rows: usize,
        cols: usize,
    ) -> PyResult<NativeBatch> {
        let batch = masks.len();
        let mask_values: Vec<bool> = masks.iter().flatten().copied().collect();
        let obs = TensorRef::from_array_view(([batch, rows, cols], obs))
            .map_err(|err| PyRuntimeError::new_err(format!("create ONNX obs tensor: {err}")))?;
        let mask = TensorRef::from_array_view((
            [batch, crate::consts::ACTION_SPACE],
            mask_values.as_slice(),
        ))
        .map_err(|err| PyRuntimeError::new_err(format!("create ONNX mask tensor: {err}")))?;

        let mut session = self
            .session
            .lock()
            .map_err(|_| PyRuntimeError::new_err("ONNX session mutex was poisoned"))?;
        let outputs = session
            .run(ort::inputs!["obs" => obs, "mask" => mask])
            .map_err(|err| PyRuntimeError::new_err(format!("ONNX inference: {err}")))?;
        let (_, values) = outputs["q_values"]
            .try_extract_tensor::<f32>()
            .map_err(|err| PyRuntimeError::new_err(format!("extract ONNX q_values: {err}")))?;
        if values.len() != batch * crate::consts::ACTION_SPACE {
            return Err(PyRuntimeError::new_err(format!(
                "unexpected ONNX output size: {}, expected {}",
                values.len(),
                batch * crate::consts::ACTION_SPACE
            )));
        }

        let q_values: Vec<Vec<f32>> = values
            .chunks_exact(crate::consts::ACTION_SPACE)
            .map(<[f32]>::to_vec)
            .collect();
        let actions = q_values
            .iter()
            .map(|values| {
                let mut best_index = 0;
                let mut best_value = f32::NEG_INFINITY;
                for (index, &value) in values.iter().enumerate() {
                    if value > best_value {
                        best_index = index;
                        best_value = value;
                    }
                }
                best_index
            })
            .collect();
        Ok(NativeBatch { actions, q_values })
    }
}
