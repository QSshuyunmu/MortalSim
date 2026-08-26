mod board;
mod custom_kyoku;
mod game;
mod mortal_onnx;
mod one_vs_three;
mod result;
mod two_vs_two;
pub(crate) mod prefix;
pub(crate) mod weighted;

pub use board::Board;
pub use result::GameResult;

use crate::py_helper::add_submodule;
use custom_kyoku::CustomKyokuRunner;
use mortal_onnx::MortalOnnxEngine;
use one_vs_three::OneVsThree;
use two_vs_two::TwoVsTwo;

use pyo3::prelude::*;

pub(crate) fn register_module(
    py: Python<'_>,
    prefix: &str,
    super_mod: &Bound<'_, PyModule>,
) -> PyResult<()> {
    let m = PyModule::new(py, "arena")?;
    m.add_class::<OneVsThree>()?;
    m.add_class::<TwoVsTwo>()?;
    m.add_class::<CustomKyokuRunner>()?;
    m.add_class::<MortalOnnxEngine>()?;
    add_submodule(py, prefix, super_mod, &m)
}
