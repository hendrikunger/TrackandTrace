"""Offline label printer test for SLF Track and Trace Windows stations.

Copy this file to the printing station and run it from PowerShell.
It uses the installed slf_trace label-printer code, but does not need the
station server to be reachable.
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from pathlib import Path

from slf_trace.companion.label_printer import (
    LabelMeasurementValue,
    LabelPrinterConfig,
    LabelReplacementRule,
    load_label_template,
    print_label_content,
    render_label_template,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render or print one offline SLF label.")
    parser.add_argument("--template", required=True, help="Full path to the .prn template.")
    parser.add_argument("--rueckmeldenummer", default="TEST-123456")
    parser.add_argument("--measurement-type", default="breite")
    parser.add_argument("--value", default="12.3400")
    parser.add_argument("--unit", default="mm")
    parser.add_argument(
        "--search",
        required=True,
        help="Exact placeholder/text in the template that should be replaced.",
    )
    parser.add_argument(
        "--replace",
        default="{{value}}",
        help="Replacement expression, e.g. {{value}}, {{value_comma}}, {{value_dot}}, "
        "{{value_raw}}, {{unit}}, {{rueckmeldenummer}}.",
    )
    parser.add_argument(
        "--value-format",
        default="comma",
        choices=["comma", "dot", "raw", "with_unit"],
    )
    parser.add_argument("--encoding", default="cp1252")
    parser.add_argument(
        "--backend",
        default="win32print",
        choices=["preview", "win32print", "tcp"],
        help="Use preview to render only, without printing.",
    )
    parser.add_argument("--printer-name", default="Vario III 107/12")
    parser.add_argument("--tcp-host", default="")
    parser.add_argument("--tcp-port", type=int, default=9100)
    parser.add_argument(
        "--output",
        default="rendered_test_label.prn",
        help="Where to write the rendered PRN for inspection.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    template_path = Path(args.template)
    config = LabelPrinterConfig(
        template_dir=template_path.parent,
        selected_template=template_path.name,
        encoding=args.encoding,
        print_backend="tcp" if args.backend == "tcp" else "win32print",
        printer_name=args.printer_name,
        tcp_host=args.tcp_host or None,
        tcp_port=args.tcp_port,
        replacements=[
            LabelReplacementRule(
                measurement_type=args.measurement_type,
                search=args.search,
                replace=args.replace,
                value_format=args.value_format,
            )
        ],
    )
    rendered = render_label_template(
        load_label_template(config),
        rueckmeldenummer=args.rueckmeldenummer,
        values=[
            LabelMeasurementValue(
                measurement_type=args.measurement_type,
                value=Decimal(args.value),
                unit=args.unit,
            )
        ],
        rules=config.replacements,
    )
    output_path = Path(args.output)
    output_path.write_text(rendered.content, encoding=args.encoding)

    print(f"Rendered: {output_path.resolve()}")
    print(f"Printable: {rendered.printable}")
    print(f"Replacements: {rendered.replaced_count}")
    if rendered.missing_blocked:
        print(f"Missing blocked: {', '.join(rendered.missing_blocked)}")
    if not rendered.printable:
        raise SystemExit(2)

    if args.backend == "preview":
        print("Preview only; no print job sent.")
        return

    destination = await print_label_content(config, rendered.content)
    print(f"Print sent: {destination}")


if __name__ == "__main__":
    asyncio.run(main())
