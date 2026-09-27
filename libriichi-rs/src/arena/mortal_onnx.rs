use std::path::PathBuf;
use std::sync::{Arc, Mutex};

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
    // ort rc.12 的 Session::run 需要 &mut，故用 Mutex；
    // Arc 共享是为了在 GIL 之外锁会话执行推理（锁等待不占用 GIL）。
    session: Arc<Mutex<Session>>,
    version: u32,
    name: String,
    enable_rule_based_agari_guard: bool,
}

#[pymethods]
impl MortalOnnxEngine {
    #[new]
    #[pyo3(signature = (model_path, device_id = 0, enable_rule_based_agari_guard = true, intra_threads = 3, name = None))]
    fn new(
        model_path: PathBuf,
        device_id: i32,
        enable_rule_based_agari_guard: bool,
        intra_threads: usize,
        name: Option<String>,
    ) -> PyResult<Self> {
        if !model_path.is_file() {
            return Err(PyValueError::new_err(format!(
                "ONNX model does not exist: {}",
                model_path.display()
            )));
        }
        // 无 CUDA 环境（如 Atozuke 纯 Intel CPU）优先使用 CPU EP；
        // 原实现硬编码 CUDA provider，在无 NVIDIA 驱动时会构建失败。
        let _ = device_id;
        let cpu = ep::CPU::default().build().error_on_failure();
        let builder = Session::builder()
            .map_err(|err| PyRuntimeError::new_err(format!("create ONNX session: {err}")))?;
        let mut builder = builder
            .with_intra_threads(intra_threads.max(1))
            .map_err(|err| PyRuntimeError::new_err(format!("set ONNX intra threads: {err}")))?
            .with_inter_threads(1)
            .map_err(|err| PyRuntimeError::new_err(format!("set ONNX inter threads: {err}")))?
            .with_execution_providers([cpu])
            .map_err(|err| {
                PyRuntimeError::new_err(format!("register ONNX CPU provider: {err}"))
            })?;
        let session = builder
            .commit_from_file(&model_path)
            .map_err(|err| PyRuntimeError::new_err(format!("load ONNX model: {err}")))?;
        Ok(Self {
            session: Arc::new(Mutex::new(session)),
            version: 4,
            name: name.unwrap_or_else(|| "MortalOnnx".to_string()),
            enable_rule_based_agari_guard,
        })
    }

    #[getter]
    fn engine_type(&self) -> &'static str {
        "mortal"
    }

    #[getter]
    fn name(&self) -> &str {
        &self.name
    }

    #[getter]
    fn is_oracle(&self) -> bool {
        false
    }

    #[getter]
    fn enable_quick_eval(&self) -> bool {
        true
    }

    #[getter]
    fn version(&self) -> u32 {
        self.version
    }

    #[getter]
    fn enable_rule_based_agari_guard(&self) -> bool {
        self.enable_rule_based_agari_guard
    }

    /// Python 侧直接推理（基准测试用）：obs 展平 + 每行 46 布尔掩码。
    fn infer_direct(
        &self,
        obs: Vec<f32>,
        masks: Vec<Vec<bool>>,
        rows: usize,
        cols: usize,
    ) -> PyResult<(Vec<usize>, Vec<Vec<f32>>)> {
        let batch = crate::arena::mortal_onnx::infer_batch(
            &self.session,
            &obs,
            &masks
                .iter()
                .map(|m| {
                    let mut arr = [false; crate::consts::ACTION_SPACE];
                    for (i, v) in m.iter().enumerate().take(crate::consts::ACTION_SPACE) {
                        arr[i] = *v;
                    }
                    arr
                })
                .collect::<Vec<_>>(),
            rows,
            cols,
        )?;
        Ok((batch.actions, batch.q_values))
    }
}

impl MortalOnnxEngine {
    // 在 GIL 内仅克隆 Arc 句柄（纳秒级）；会话锁的等待发生在 GIL 之外。
    pub(crate) fn session_arc(&self) -> Arc<Mutex<Session>> {
        Arc::clone(&self.session)
    }
}

// 自由函数：不触碰任何 Python 对象，可在无 GIL 环境下调用。
pub(crate) fn infer_batch(
    session: &Mutex<Session>,
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

        let mut session = session
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
