"""Command-line interface for the citation checker."""

import argparse
import sys
from pathlib import Path
from typing import Optional

from .pipeline import CitationChecker


def main(args: Optional[list] = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Legal Citation Checker - Verify citation authenticity in DOCX and PDF documents"
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Path to DOCX file to check",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file for audit report (default: stdout)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["markdown", "html", "json"],
        default="markdown",
        help="Output format for audit report",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="API request timeout in seconds (default: 8)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable verification result caching",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="legal-citation-checker 0.1.0",
    )

    parsed_args = parser.parse_args(args)

    # Check if file exists
    if not parsed_args.input_file.exists():
        print(f"Error: File not found: {parsed_args.input_file}", file=sys.stderr)
        return 1

    # Check if it's a supported file type
    if parsed_args.input_file.suffix.lower() not in (".docx", ".pdf"):
        print(f"Error: Only DOCX and PDF files are supported", file=sys.stderr)
        return 1

    try:
        checker = CitationChecker(
            verbose=parsed_args.verbose,
            request_timeout=parsed_args.timeout,
            disable_cache=parsed_args.no_cache,
        )
        report = checker.process_document(parsed_args.input_file)
        
        if parsed_args.output:
            report.save(parsed_args.output, format=parsed_args.format)
            print(f"Report saved to: {parsed_args.output}")
        else:
            print(report.to_string(format=parsed_args.format))
            
        return 0
        
    except Exception as e:
        print(f"Error processing document: {e}", file=sys.stderr)
        if parsed_args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())