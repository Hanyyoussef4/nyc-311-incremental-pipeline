import os
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

APP_TOKEN = os.getenv("NYC_311_APP_TOKEN")
BASE_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"

headers = {"X-App-Token": APP_TOKEN}

params = {
    "$select": '*',
     }
respose = requests.get(BASE_URL, headers=headers, params=params)
data=respose.json()
df = pd.DataFrame(data)
print(df.isnull().sum())
print(df.count())



# params = {
#     "$select": 'complaint_type, count(*)',
#     "$group": 'complaint_type',
#      }

# response = requests.get(BASE_URL, headers=headers, params=params)
# data=response.json()
# # print(data)
# print(len(data))
# df = pd.DataFrame(data)
# list1= df['complaint_type'].str.strip().str.lower()
# print(list1.duplicated().sum())
# print(list1.duplicated().nunique())
# print(list1.nunique())
# counts = list1.value_counts()
# print(counts[counts > 1])

# for row in data:
#     print(row.get('complaint_type', 'missing/none'), row['count'])

