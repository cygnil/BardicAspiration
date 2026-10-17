import ast
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import weakref

import numpy as np


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "bin" / "transcribe.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        self.whisperx = Mock()
        self.namespace = {
            "gc": gc, "hashlib": hashlib, "json": json, "math": math,
            "os": os, "subprocess": Mock(), "np": np, "whisperx": self.whisperx,
            "torch": SimpleNamespace(cuda=SimpleNamespace(
                is_available=lambda: False,
                OutOfMemoryError=type("OutOfMemoryError", (RuntimeError,), {}),
            )),
        }
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), self.namespace)

    def test_batch_retry_and_unrelated_errors(self):
        model = Mock()
        model.transcribe.side_effect = [RuntimeError("CUDA out of memory"), RuntimeError("CUDA out of memory"), {"segments": []}]
        result = self.namespace["transcribe_with_retry"](model, np.zeros(1), 4)
        self.assertEqual(result, {"segments": []})
        self.assertEqual([call.kwargs["batch_size"] for call in model.transcribe.call_args_list], [4, 2, 1])
        model.transcribe.side_effect = RuntimeError("invalid audio")
        with self.assertRaisesRegex(RuntimeError, "invalid audio"):
            self.namespace["transcribe_with_retry"](model, np.zeros(1), 4)

    def test_overlap_ownership_and_offsets(self):
        segment = {"start": 1, "end": 4, "text": "old new", "words": [
            {"word": "old", "start": 1, "end": 2},
            {"word": "new", "start": 3, "end": 4},
        ]}
        left = self.namespace["merge_window_segments"]([segment], 298, 0, 300, np.zeros(80000))
        right = self.namespace["merge_window_segments"]([segment], 298, 300, 600, np.zeros(80000))
        self.assertEqual([left[0]["text"], right[0]["text"]], ["old", "new"])
        self.assertEqual(right[0]["start"], 301)
        self.assertEqual(right[0]["words"][0]["end"], 302)
        self.assertEqual(segment["words"][0]["start"], 1)

    def test_two_pass_lifetime_and_resume(self):
        self.namespace["subprocess"].run.return_value.stdout = json.dumps({"format": {"duration": "601"}})
        self.namespace["load_audio_window"] = Mock(return_value=(np.zeros(16000), np.zeros(16000)))
        references = []

        def load_model(*args, **kwargs):
            model = Mock()
            model.transcribe.return_value = {"segments": [{"start": 2, "end": 3, "text": "hello"}]}
            references.append(weakref.ref(model))
            return model

        def load_alignment(**kwargs):
            self.assertTrue(all(reference() is None for reference in references))
            return Mock(), {}

        self.whisperx.load_model.side_effect = load_model
        self.whisperx.load_align_model.side_effect = load_alignment
        self.whisperx.align.side_effect = lambda transcript, *args, **kwargs: {"segments": transcript}
        with tempfile.TemporaryDirectory() as directory:
            with tempfile.NamedTemporaryFile(dir=directory) as source:
                options = dict(audio_path=source.name, device="cuda", compute_type="int8_float16", checkpoint_dir=directory)
                segments, duration = self.namespace["transcribe_and_align"](**options)
                self.assertEqual(duration, 601)
                self.assertEqual([segment["start"] for segment in segments], [2, 300, 600])
                self.assertEqual(self.whisperx.align.call_count, 3)
                self.whisperx.reset_mock()
                resumed, _ = self.namespace["transcribe_and_align"](**options, resume=True)
                self.assertEqual(resumed, segments)
                self.whisperx.load_model.assert_not_called()
                self.whisperx.load_align_model.assert_not_called()

    def test_cpu_fallback_and_partial_resume(self):
        self.namespace["subprocess"].run.return_value.stdout = json.dumps({"format": {"duration": "10"}})
        self.namespace["load_audio_window"] = Mock(return_value=(np.zeros(16000), np.zeros(16000)))
        gpu_model, cpu_model = Mock(), Mock()
        gpu_model.transcribe.side_effect = RuntimeError("CUDA out of memory")
        cpu_model.transcribe.return_value = {"segments": [{"start": 0, "end": 1, "text": "hello"}]}
        self.whisperx.load_model.side_effect = [gpu_model, cpu_model]
        self.whisperx.load_align_model.return_value = (Mock(), {})
        self.whisperx.align.side_effect = RuntimeError("alignment interrupted")
        with tempfile.TemporaryDirectory() as directory:
            with tempfile.NamedTemporaryFile(dir=directory) as source:
                options = dict(audio_path=source.name, device="cuda", compute_type="int8_float16", checkpoint_dir=directory)
                with self.assertRaisesRegex(RuntimeError, "alignment interrupted"):
                    self.namespace["transcribe_and_align"](**options)
                self.assertEqual(self.whisperx.load_model.call_args_list[-1].args[1], "cpu")
                self.whisperx.reset_mock()
                self.whisperx.align.side_effect = lambda transcript, *args, **kwargs: {"segments": transcript}
                segments, _ = self.namespace["transcribe_and_align"](**options, resume=True)
                self.whisperx.load_model.assert_not_called()
                self.assertEqual(segments[0]["text"], "hello")

    def test_alignment_cpu_fallback(self):
        self.namespace["subprocess"].run.return_value.stdout = json.dumps({"format": {"duration": "10"}})
        self.namespace["load_audio_window"] = Mock(return_value=(np.zeros(16000), np.zeros(16000)))
        self.whisperx.load_model.return_value.transcribe.return_value = {
            "segments": [{"start": 0, "end": 1, "text": "hello"}],
        }
        alignment_model = Mock()
        self.whisperx.load_align_model.return_value = (alignment_model, {})
        self.whisperx.align.side_effect = [RuntimeError("CUDA out of memory"), {
            "segments": [{"start": 0, "end": 1, "text": "hello"}],
        }]
        with tempfile.TemporaryDirectory() as directory:
            with tempfile.NamedTemporaryFile(dir=directory) as source:
                segments, _ = self.namespace["transcribe_and_align"](
                    source.name, "cuda", "int8_float16", directory,
                )
                alignment_model.to.assert_called_once_with("cpu")
                self.assertEqual(self.whisperx.align.call_args.args[4], "cpu")
                self.assertEqual(len(segments), 1)

    def test_model_loading_cpu_fallback(self):
        self.whisperx.load_model.side_effect = [RuntimeError("CUDA out of memory"), Mock()]
        _, device, precision = self.namespace["load_transcription_model"]("large-v3", "cuda", "int8_float16", "names")
        self.assertEqual((device, precision), ("cpu", "int8"))

    def test_ffmpeg_window_decode_and_gating(self):
        self.namespace["subprocess"] = subprocess
        with tempfile.TemporaryDirectory() as directory:
            audio_path = os.path.join(directory, "tone.wav")
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=3", audio_path,
            ], check=True)
            audio, db = self.namespace["load_audio_window"](audio_path, 1, 1, None)
            self.assertEqual(len(audio), 16000)
            self.assertGreater(float(np.max(audio)), 0)
            gated, _ = self.namespace["load_audio_window"](audio_path, 1, 1, 0)
            self.assertTrue(np.all(gated == 0))
            self.assertEqual(len(db), len(audio))


if __name__ == "__main__":
    unittest.main()