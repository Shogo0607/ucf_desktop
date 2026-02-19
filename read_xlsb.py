import pandas as pd

# xlsbファイルを読み込む関数
def read_xlsb(file_path, sheet_name=None):
    # sheet_nameがNoneの場合はすべてのシートを読み込む
    with pd.ExcelFile(file_path, engine='pyxlsb') as xls:
        if sheet_name is None:
            sheets = xls.sheet_names
            dfs = {sheet: pd.read_excel(xls, sheet_name=sheet, engine='pyxlsb') for sheet in sheets}
            return dfs
        else:
            df = pd.read_excel(xls, sheet_name=sheet_name, engine='pyxlsb')
            return df

# 読み込み実行
if __name__ == '__main__':
    file_path = 'Book3.xlsb'
    result = read_xlsb(file_path)
    for sheet, df in result.items():
        print(f"Sheet: {sheet}")
        print(df.head())
        print('-----')
