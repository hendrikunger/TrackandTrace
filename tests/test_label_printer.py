from decimal import Decimal

from slf_trace.companion.label_printer import (
    LabelMeasurementValue,
    LabelReplacementRule,
    render_label_template,
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
