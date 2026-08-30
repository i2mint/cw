"""`cw.egress`: what a return value becomes, and where it lands.

The half of these tests that asks "is this what argh does" lives in
`tests/argh_parity/test_cli_parity.py`, where argh answers for itself. What is here is the
half argh cannot answer: cw's own additions, and the stream discipline that is the whole
reason a cw CLI is testable and an argh CLI is not.
"""

import io
import sys

import pytest

import cw
from cw.egress import guard_no_coroutine, write_lines


class TestStreamsResolveAtCallTime:
    """argh binds `output_file=sys.stdout` in a signature default; cw looks it up now.

    That one difference is why `capsys`, `redirect_stdout` and a plain `out=` all work.
    """

    def test_out_captures_everything(self):
        buffer = io.StringIO()
        assert cw.argh_egress(["a", "b"], out=buffer) == 0
        assert buffer.getvalue() == "a\nb\n"

    def test_capsys_captures_a_whole_dispatch(self, capsys):
        cw.dispatch(lambda: ["one", "two"], [])
        assert capsys.readouterr().out == "one\ntwo\n"

    def test_redirect_stdout_captures_a_whole_dispatch(self):
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cw.dispatch(lambda: "hi", [])
        assert buffer.getvalue() == "hi\n"

    def test_no_stream_is_bound_in_a_signature_default(self):
        """The defect being avoided, asserted at the signature rather than in prose."""
        import inspect

        for func in (cw.argh_egress, cw.iterable_egress, cw.json_egress, cw.confirm):
            for parameter in inspect.signature(func).parameters.values():
                assert parameter.default is not sys.stdout, func
                assert parameter.default is not sys.stderr, func


class TestWriteLines:
    def test_writes_str_of_each_item(self):
        buffer = io.StringIO()
        write_lines([1, None, "x"], out=buffer)
        assert buffer.getvalue() == "1\nNone\nx\n"

    def test_is_lazy(self):
        """Row 18: a generator's output must land before the command's next prompt."""
        buffer = io.StringIO()
        seen = []

        def lines():
            yield "first"
            seen.append(buffer.getvalue())
            yield "second"

        write_lines(lines(), out=buffer)
        assert seen == ["first\n"]

    def test_flushes_each_line(self):
        class Counting(io.StringIO):
            flushes = 0

            def flush(self):
                type(self).flushes += 1

        buffer = Counting()
        write_lines(["a", "b"], out=buffer)
        assert Counting.flushes == 2

    def test_flush_can_be_turned_off(self):
        class Counting(io.StringIO):
            flushes = 0

            def flush(self):
                type(self).flushes += 1

        write_lines(["a", "b"], out=Counting(), flush=False)
        assert Counting.flushes == 0


class TestWhichResultsAreLines:
    """The single difference between `argh_egress` and `iterable_egress`."""

    @pytest.mark.parametrize(
        "result, argh_lines, modern_lines",
        [
            ([1, 2], "1\n2\n", "1\n2\n"),
            ((1, 2), "1\n2\n", "1\n2\n"),
            ({"a": 1}, "{'a': 1}\n", "{'a': 1}\n"),
            ("two words", "two words\n", "two words\n"),
            (b"bytes", "b'bytes'\n", "b'bytes'\n"),
            (None, "", ""),
            (0, "0\n", "0\n"),
            (False, "False\n", "False\n"),
            ("", "\n", "\n"),
        ],
    )
    def test_agree_except_on_the_protocol(self, result, argh_lines, modern_lines):
        for egress, expected in (
            (cw.argh_egress, argh_lines),
            (cw.iterable_egress, modern_lines),
        ):
            buffer = io.StringIO()
            egress(result, out=buffer)
            assert buffer.getvalue() == expected, egress

    def test_a_set_is_one_line_for_argh_and_several_for_modern(self):
        buffer = io.StringIO()
        cw.argh_egress({7}, out=buffer)
        assert buffer.getvalue() == "{7}\n"
        buffer = io.StringIO()
        cw.iterable_egress({7}, out=buffer)
        assert buffer.getvalue() == "7\n"

    def test_a_generator_is_lines_for_both(self):
        def lines():
            yield "a"
            yield "b"

        for egress in (cw.argh_egress, cw.iterable_egress):
            buffer = io.StringIO()
            egress(lines(), out=buffer)
            assert buffer.getvalue() == "a\nb\n", egress

    def test_a_plain_iterator_is_NOT_a_generator(self):
        """The sharpest edge of the whitelist, verified against live argh.

        argh tests for `GeneratorType`, so `iter([...])` -- a `list_iterator` -- prints
        its repr rather than its items.
        """
        buffer = io.StringIO()
        cw.argh_egress(iter(["a", "b"]), out=buffer)
        assert buffer.getvalue().startswith("<list_iterator object at")
        buffer = io.StringIO()
        cw.iterable_egress(iter(["a", "b"]), out=buffer)
        assert buffer.getvalue() == "a\nb\n"


class TestJsonEgress:
    def test_writes_one_document(self):
        buffer = io.StringIO()
        assert cw.json_egress({"b": [1]}, out=buffer, indent=None) == 0
        assert buffer.getvalue() == '{"b": [1]}\n'

    def test_materialises_an_iterator(self):
        buffer = io.StringIO()
        cw.json_egress(iter([1, 2]), out=buffer, indent=None)
        assert buffer.getvalue() == "[1, 2]\n"

    def test_falls_back_to_str_rather_than_raising(self):
        buffer = io.StringIO()
        cw.json_egress({"when": object()}, out=buffer, indent=None)
        assert buffer.getvalue().startswith('{"when": "<object object at')

    def test_none_writes_nothing(self):
        buffer = io.StringIO()
        cw.json_egress(None, out=buffer)
        assert buffer.getvalue() == ""


class TestCoroutineGuard:
    """v1 runs no event loop, and says so rather than printing `<coroutine object ...>`."""

    def test_names_asyncio_run(self):
        async def fetch():
            return 1

        with pytest.raises(TypeError, match="asyncio.run"):
            guard_no_coroutine(fetch())

    @pytest.mark.parametrize(
        "egress", [None, cw.argh_egress, cw.iterable_egress, cw.json_egress]
    )
    def test_fires_whichever_egress_is_selected(self, egress):
        """The check is at the call site, so no egress choice can switch it off."""

        async def fetch():
            return 1

        with pytest.raises(TypeError, match="coroutine"):
            cw.dispatch(fetch, [], egress=egress, out=io.StringIO())

    def test_a_plain_result_passes_through(self):
        assert guard_no_coroutine([1, 2]) is None


class TestConfirm:
    @pytest.mark.parametrize(
        "default, typed, expected",
        [
            (None, "y\n", True),
            (None, "Y\n", True),
            (None, "yes\n", True),
            (None, "n\n", False),
            (None, "no\n", False),
            (None, "garbage\n", None),
            (True, "\n", True),
            (True, "garbage\n", True),
            (False, "\n", False),
            (False, "y\n", True),
        ],
    )
    def test_answers(self, default, typed, expected):
        assert (
            cw.confirm("Go", default=default, in_=io.StringIO(typed), out=io.StringIO())
            is expected
        )

    def test_an_empty_answer_with_no_default_asks_again(self):
        out = io.StringIO()
        assert cw.confirm("Go", in_=io.StringIO("\n\ny\n"), out=out) is True
        assert out.getvalue() == "Go? (y/n)" * 3

    @pytest.mark.parametrize(
        "default, prompt",
        [(None, "Go? (y/n)"), (True, "Go? (Y/n)"), (False, "Go? (y/N)")],
    )
    def test_prompt_spelling(self, default, prompt):
        """argh's exact spelling, trailing space and all -- of which there is none."""
        out = io.StringIO()
        cw.confirm("Go", default=default, in_=io.StringIO("y\n"), out=out)
        assert out.getvalue() == prompt

    def test_skip_returns_the_default_and_asks_nothing(self):
        out = io.StringIO()
        assert cw.confirm("Go", default=True, skip=True, out=out) is True
        assert out.getvalue() == ""

    def test_the_interactive_path_uses_input(self, monkeypatch):
        """With neither stream given, `input()` is used, so readline editing survives."""
        asked = []
        monkeypatch.setattr(
            "builtins.input", lambda prompt: asked.append(prompt) or "y"
        )
        assert cw.confirm("Go") is True
        assert asked == ["Go? (y/n)"]

    def test_end_of_input_raises(self):
        with pytest.raises(EOFError):
            cw.confirm("Go", in_=io.StringIO(""), out=io.StringIO())
