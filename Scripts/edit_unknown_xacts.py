import tempfile
import subprocess
import os
import sys
import re
import argparse


def edit_unknown_transactions(journal_path, date_fmt):
    with open(journal_path, "r") as file:
        content = file.read()

    transaction_boundary = re.compile(f"\n(?={date_fmt})")
    # Split the content into transactions
    transactions = re.split(transaction_boundary, content)

    unknown_transactions = []
    known_transactions = []

    for transaction in transactions:
        if "Expenses:Unknown" in transaction:
            unknown_transactions.append(transaction)
        else:
            known_transactions.append(transaction)

    if not unknown_transactions:
        print("No unknown transactions found.", file=sys.stderr)
        return

    # Create a temporary file with unknown transactions
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".journal", delete=False
    ) as temp_file:
        temp_file.write("\n\n".join(unknown_transactions))
        temp_file_path = temp_file.name

    # Open the temporary file in the user's preferred editor
    editor = os.environ.get("EDITOR", "nano")
    subprocess.call([editor, temp_file_path])

    # Read the edited unknown transactions
    with open(temp_file_path, "r") as file:
        edited_content = file.read()

    edited_transactions = re.split(transaction_boundary, edited_content)

    # Merge edited transactions back into the original content
    final_transactions = []
    unknown_index = 0

    for transaction in transactions:
        if "Expenses:Unknown" in transaction:
            if unknown_index < len(edited_transactions):
                final_transactions.append(edited_transactions[unknown_index])
                unknown_index += 1
            else:
                final_transactions.append(transaction)
        else:
            final_transactions.append(transaction)

    # Write the final content back to the original file
    with open(journal_path, "w") as file:
        file.write("\n\n".join([xact.strip() for xact in final_transactions]))

    # Clean up the temporary file
    os.unlink(temp_file_path)


def main():
    parser = argparse.ArgumentParser(
        description="Edit unknown transactions in a ledger journal file."
    )
    parser.add_argument("journal_path", type=str, help="Path to the journal file")
    parser.add_argument(
        "-d",
        "--date-format",
        metavar="REGEX",
        help="Python regex for the transaction date format",
        default=r"\d{4}/\d{2}/\d{2}",
    )
    args = parser.parse_args()

    edit_unknown_transactions(args.journal_path, args.date_format)


if __name__ == "__main__":
    main()
