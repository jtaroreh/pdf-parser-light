import argparse
import os
import sys

# Ensure stdout/stderr streams are valid even when running inside a PyInstaller --noconsole executable
if sys.stdout is None:
    try:
        sys.stdout = sys.__stdout__ or open(1, "w", encoding="utf-8", closefd=False)
    except Exception:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass

if sys.stderr is None:
    try:
        sys.stderr = sys.__stderr__ or open(2, "w", encoding="utf-8", closefd=False)
    except Exception:
        try:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass

from .parse import parse_pdf, parse_directory, PartialParseError, QuotaExceededError, validate_pdf
from . import config


def main():
    parser = argparse.ArgumentParser(
        description="PDF Parser Light - A stateless CLI to parse PDFs into Markdown using the Gemini API."
    )
    
    parser.add_argument(
        "input_path",
        nargs="?",
        help="Path to a single PDF file or a directory containing PDF files."
    )
    parser.add_argument(
        "--api-key",
        help="Gemini API Key. Overrides GEMINI_API_KEY environment variable. Recommended standard workflow is GEMINI_API_KEY env var to avoid exposing keys in shell history and process listings.",
        default=None
    )
    parser.add_argument(
        "--prompt",
        help="Custom system prompt to override the default transcription instructions.",
        default=None
    )
    parser.add_argument(
        "--output",
        help="Output directory (for batch processing) or output file (for single file). Default is same directory as input.",
        default=None
    )
    parser.add_argument(
        "--usage",
        action="store_true",
        help="Show the number of free API requests left today and exit."
    )
    parser.add_argument(
        "--reset-quota",
        "--reset-usage",
        action="store_true",
        help="Reset the local daily free quota tracker to full and exit."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore remaining quota checks and force processing."
    )
    parser.add_argument(
        "--pages",
        "-p",
        help="Page range to process (e.g. '40-120', '1-50', or '10'). Default is all pages.",
        default=None
    )
    parser.add_argument(
        "--resume",
        "-r",
        action="store_true",
        help="Resume parsing from previous partial output file instead of starting over."
    )
    
    args = parser.parse_args()

    # If --reset-quota / --reset-usage is requested, reset usage and exit immediately
    if getattr(args, "reset_quota", False) or getattr(args, "reset_usage", False):
        config.reset_usage()
        left = config.get_remaining_requests()
        print(f"Daily free quota tracker reset! Free Requests Left Today: {left} / {config.MAX_FREE_REQUESTS}")
        sys.exit(0)

    # If --usage is requested, print and exit immediately (no key needed)
    if args.usage:
        used = config.get_usage()
        left = config.get_remaining_requests()
        print(f"Free Requests Left Today: {left} / {config.MAX_FREE_REQUESTS} (Used today: {used})")
        print(f"Extended Lite Fallbacks: Available (gemini-3.5-flash-lite / gemini-3.1-flash-lite - 100+ extra reqs/day)")
        sys.exit(0)


    # If invoked with no arguments at all, launch the GUI app
    if len(sys.argv) == 1:
        from .app import main as app_main
        app_main()
        sys.exit(0)

    if not args.input_path:
        parser.error("the following arguments are required: input_path")

    # API Key Resolution (Strictly stateless, no config file reading)
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        print("Error: No Gemini API Key provided.", file=sys.stderr)
        print("Please provide it via the --api-key argument or set the GEMINI_API_KEY environment variable:", file=sys.stderr)
        print("  export GEMINI_API_KEY='your_api_key_here'", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.input_path):
        print(f"Error: Input path not found: {args.input_path}", file=sys.stderr)
        sys.exit(1)

    # Execution
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
        left = config.get_remaining_requests()
        suffix = " (Using Fallback Models)" if left <= 0 else ""
        print(f"Free API Requests Left Today: {left} / {config.MAX_FREE_REQUESTS}{suffix}")
        if fail_count > 0:
            sys.exit(1)
    elif os.path.isfile(args.input_path):
        try:
            validate_pdf(args.input_path)
        except Exception as val_err:
            print(f"Error: PDF validation failed: {val_err}", file=sys.stderr)
            sys.exit(1)

        print(f"Processing single file: {args.input_path}")
        
        # Determine output path
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
            
            left = config.get_remaining_requests()
            suffix = " (Using Fallback Models)" if left <= 0 else ""
            print(f"Free API Requests Left Today: {left} / {config.MAX_FREE_REQUESTS}{suffix}")
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

