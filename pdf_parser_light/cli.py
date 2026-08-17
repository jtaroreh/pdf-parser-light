import argparse
import os
import sys

# Ensure stdout/stderr streams are valid when running packaged without a console
if sys.stdout is None:
    try:
        sys.stdout = sys.__stdout__ or open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

if sys.stderr is None:
    try:
        sys.stderr = sys.__stderr__ or open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

from .parse import parse_pdf, parse_directory, PartialParseError, QuotaExceededError, validate_pdf
from . import config


def _print_remaining_quota():
    left = config.get_remaining_requests()
    suffix = " (Using Fallback Models)" if left <= 0 else ""
    print(f"Free API Requests Left Today: {left} / {config.MAX_FREE_REQUESTS}{suffix}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDFs into Markdown using the Gemini API."
    )
    
    parser.add_argument(
        "input_path",
        nargs="?",
        help="Path to a PDF file or directory containing PDF files."
    )
    parser.add_argument(
        "--api-key",
        help="Gemini API key (overrides GEMINI_API_KEY environment variable).",
        default=None
    )
    parser.add_argument(
        "--prompt",
        help="Custom system prompt override.",
        default=None
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path or directory.",
        default=None
    )
    parser.add_argument(
        "--pages",
        "-p",
        help="Page range to process (e.g. '1-50', '40-120', or '10').",
        default=None
    )
    parser.add_argument(
        "--resume",
        "-r",
        action="store_true",
        help="Resume parsing from existing partial output file."
    )
    parser.add_argument(
        "--usage",
        action="store_true",
        help="Show remaining daily free requests and exit."
    )
    parser.add_argument(
        "--reset-quota",
        "--reset-usage",
        action="store_true",
        dest="reset_quota",
        help="Reset daily request counter to 0 and exit."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass remaining quota check."
    )
    
    args = parser.parse_args()

    if args.reset_quota:
        config.reset_usage()
        left = config.get_remaining_requests()
        print(f"Daily free quota tracker reset! Free Requests Left Today: {left} / {config.MAX_FREE_REQUESTS}")
        sys.exit(0)

    if args.usage:
        used = config.get_usage()
        left = config.get_remaining_requests()
        print(f"Free Requests Left Today: {left} / {config.MAX_FREE_REQUESTS} (Used today: {used})")
        print("Extended Lite Fallbacks: Available (gemini-3.5-flash-lite / gemini-3.1-flash-lite - 100+ extra reqs/day)")
        sys.exit(0)

    if len(sys.argv) == 1:
        from .app import main as app_main
        app_main()
        sys.exit(0)

    if not args.input_path:
        parser.error("the following arguments are required: input_path")

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: No Gemini API Key provided.", file=sys.stderr)
        print("Please provide it via --api-key or set the GEMINI_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.input_path):
        print(f"Error: Input path not found: {args.input_path}", file=sys.stderr)
        sys.exit(1)

    if os.path.isdir(args.input_path):
        print(f"Batch processing directory: {args.input_path}")
        _, fail_count = parse_directory(
            api_key=api_key,
            directory_path=args.input_path,
            output_dir=args.output,
            custom_prompt=args.prompt,
            ignore_quota=args.force,
            page_range=args.pages,
            resume=args.resume
        )
        _print_remaining_quota()
        if fail_count > 0:
            sys.exit(1)

    elif os.path.isfile(args.input_path):
        try:
            validate_pdf(args.input_path)
        except Exception as val_err:
            print(f"Error: PDF validation failed: {val_err}", file=sys.stderr)
            sys.exit(1)

        print(f"Processing single file: {args.input_path}")
        
        if args.output:
            if os.path.isdir(args.output):
                base_name = os.path.splitext(os.path.basename(args.input_path))[0]
                out_path = os.path.join(args.output, f"{base_name}.md")
            else:
                out_path = args.output
        else:
            base_name = os.path.splitext(args.input_path)[0]
            out_path = f"{base_name}.md"

        try:
            md_content = parse_pdf(
                api_key=api_key, 
                file_path=args.input_path,
                custom_prompt=args.prompt,
                ignore_quota=args.force,
                page_range=args.pages,
                resume=args.resume,
                output_path=out_path
            )
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            print(f"Successfully saved to {out_path}")
            _print_remaining_quota()
        except PartialParseError as ppe:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(ppe.partial_text)
            print(f"Warning: Mid-chunk failure occurred ({ppe.original_error}). Partial transcription saved to {out_path}", file=sys.stderr)
            sys.exit(1)
        except QuotaExceededError as qee:
            print(f"Error: {qee}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Failed to process PDF: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Error: Invalid input path.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
