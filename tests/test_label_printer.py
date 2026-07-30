import sys
from decimal import Decimal
from types import SimpleNamespace

import pytest

from slf_trace.companion.label_printer import (
    LabelMeasurementValue,
    LabelPrinterConfig,
    LabelReplacementRule,
    print_label_win32,
    render_label_template,
    win32_printer_info,
)


def test_render_label_template_replaces_value_with_selected_format() -> None:
    rendered = render_label_template(
        "BM[15]-283",
        rueckmeldenummer="RM-1",
        values=[
            LabelMeasurementValue(
                measurement_type="breite",
                value=Decimal("32.4000"),
                unit="mm",
            )
        ],
        rules=[
            LabelReplacementRule(
                measurement_type="breite",
                search="BM[15]-283",
                replace="BM[15]{{value}}",
                value_format="comma",
            )
        ],
    )

    assert rendered.printable
    assert rendered.content == "BM[15]32,4000"
    assert rendered.replaced_count == 1


def test_render_label_template_warn_allow_print_uses_space_for_missing_value() -> None:
    rendered = render_label_template(
        "BM[16]1,5",
        rueckmeldenummer="RM-1",
        values=[],
        rules=[
            LabelReplacementRule(
                measurement_type="ueberstand",
                search="BM[16]1,5",
                replace="BM[16]{{value}}",
                missing_value_behavior="warn_allow_print",
            )
        ],
        allow_missing_values=True,
    )

    assert rendered.printable
    assert rendered.content == "BM[16] "
    assert rendered.missing_warned == ["ueberstand"]


def test_render_label_template_blocks_missing_values_by_default() -> None:
    rendered = render_label_template(
        "BM[16]1,5",
        rueckmeldenummer="RM-1",
        values=[],
        rules=[
            LabelReplacementRule(
                measurement_type="ueberstand",
                search="BM[16]1,5",
                replace="BM[16]{{value}}",
            )
        ],
    )

    assert not rendered.printable
    assert rendered.missing_blocked == ["ueberstand"]


def test_print_label_win32_reports_job_and_byte_count(monkeypatch) -> None:
    calls = []

    fake_win32print = SimpleNamespace(
        OpenPrinter=lambda name: f"handle:{name}",
        StartDocPrinter=lambda handle, level, doc_info: 123,
        StartPagePrinter=lambda handle: calls.append(("start_page", handle)),
        WritePrinter=lambda handle, payload: len(payload),
        EndPagePrinter=lambda handle: calls.append(("end_page", handle)),
        EndDocPrinter=lambda handle: calls.append(("end_doc", handle)),
        ClosePrinter=lambda handle: calls.append(("close", handle)),
    )
    monkeypatch.setitem(sys.modules, "win32print", fake_win32print)

    destination = print_label_win32(
        LabelPrinterConfig(
            template_dir=".",
            selected_template="label.prn",
            printer_name="Vario III 107/12",
        ),
        b"abc",
    )

    assert destination == "win32print:Vario III 107/12:job:123:bytes:3"
    assert ("close", "handle:Vario III 107/12") in calls


def test_print_label_win32_rejects_partial_write(monkeypatch) -> None:
    fake_win32print = SimpleNamespace(
        OpenPrinter=lambda name: f"handle:{name}",
        StartDocPrinter=lambda handle, level, doc_info: 123,
        StartPagePrinter=lambda handle: None,
        WritePrinter=lambda handle, payload: 2,
        EndPagePrinter=lambda handle: None,
        EndDocPrinter=lambda handle: None,
        ClosePrinter=lambda handle: None,
    )
    monkeypatch.setitem(sys.modules, "win32print", fake_win32print)

    with pytest.raises(RuntimeError, match="accepted 2 of 3"):
        print_label_win32(
            LabelPrinterConfig(
                template_dir=".",
                selected_template="label.prn",
                printer_name="Vario III 107/12",
            ),
            b"abc",
        )


def test_win32_printer_info_returns_driver_port_and_queue_details(monkeypatch) -> None:
    fake_win32print = SimpleNamespace(
        OpenPrinter=lambda name: f"handle:{name}",
        GetPrinter=lambda handle, level: {
            "pPrinterName": "Vario III 107/12",
            "pDriverName": "Carl Valentin Vario",
            "pPortName": "USB001",
            "Status": 0,
            "Attributes": 64,
            "cJobs": 1,
        },
        ClosePrinter=lambda handle: None,
    )
    monkeypatch.setitem(sys.modules, "win32print", fake_win32print)

    info = win32_printer_info(
        LabelPrinterConfig(
            template_dir=".",
            selected_template="label.prn",
            printer_name="Vario III 107/12",
        )
    )

    assert info == {
        "printer_name": "Vario III 107/12",
        "driver_name": "Carl Valentin Vario",
        "port_name": "USB001",
        "status": 0,
        "attributes": 64,
        "jobs": 1,
    }
