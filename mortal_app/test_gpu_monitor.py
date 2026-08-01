import unittest

from .gpu_monitor import assess_sample, parse_nvidia_smi_line


class GpuMonitorTests(unittest.TestCase):
    def test_parse_csv_sample(self):
        sample = parse_nvidia_smi_line("54, 35, 667, 6141, 7.5, 80, 675")
        self.assertIsNotNone(sample)
        self.assertEqual(sample["temperature.gpu"], 54)
        self.assertEqual(sample["memory.total"], 6141)

    def test_thresholds(self):
        sample = parse_nvidia_smi_line("90, 99, 5900, 6141, 79, 80, 1000")
        self.assertEqual(assess_sample(sample)[0], "critical")


if __name__ == "__main__":
    unittest.main()
