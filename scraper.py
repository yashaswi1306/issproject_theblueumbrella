import csv
import base64
import requests
import pymysql
from pymongo import MongoClient
from dotenv import load_dotenv
import os
from mongo_db import upsert_image
from my_sql import insert_user



f=open("batch_data.csv","r")
reader_obj=csv.DictReader(f)
for row in reader_obj:
    u_id=row["uid"]
    name=row["name"]
    website_url=row["website_url"]
    website_url = website_url.rstrip("/")
    if not website_url.startswith("http"):
        website_url = "https://" + website_url
    url=f"{website_url}/images/pfp.jpg"
    try:
        insert_user(u_id,name)
        action=requests.get(url,timeout=15)
        if(action.status_code==404):
            print(f"404 Error: Image NOT FOUND for {name}")
            continue
        action.raise_for_status()
        key= base64.b64encode(action.content).decode("utf-8")
        upsert_image(u_id,key)
        print(f"Successfull:{name}")
    except Exception as e:
        print(f"Error for {name}: {e}")


