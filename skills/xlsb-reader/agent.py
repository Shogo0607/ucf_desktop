import pandas as pd


def get_sheet_names(file_path):
    xls = pd.ExcelFile(file_path, engine='pyxlsb')
    return xls.sheet_names


def main(file_path):
    sheets = get_sheet_names(file_path)
    print(f"Sheets in {file_path}: {sheets}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: agent.py <xlsb_file_path>")
        sys.exit(1)
    main(sys.argv[1])
