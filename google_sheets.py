import gspread
from google.oauth2.service_account import Credentials

# Путь к вашему JSON-файлу
SERVICE_ACCOUNT_FILE = "credentials.json"

# Области доступа (разрешает только чтение Google Sheets)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Авторизация
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
client = gspread.authorize(creds)

# ID вашей таблицы (из URL)
SPREADSHEET_ID = "1G3QYC8oQHAqGUfewK85BHjYsfKttyzC6CKa75DCuPj4"

# Открываем таблицу и получаем данные
sheet = client.open_by_key(SPREADSHEET_ID).sheet1  # Первая вкладка
data = sheet.get_all_records()

# Выводим данные
for row in data:
    print(row)
