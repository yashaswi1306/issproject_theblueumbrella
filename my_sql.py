
import pymysql
# from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

mysql_conn=pymysql.connect(
    host="localhost",
    user="root",
    password=os.getenv("MYSQL_PASSWORD"),
    # root1234 for me
    database="arena_db"
)


mysql_cursor=mysql_conn.cursor()


def insert_user(uid,name):
    query="INSERT IGNORE INTO users (uid,name) VALUES (%s,%s)"
    mysql_cursor.execute(query,(uid,name))
    mysql_conn.commit()

def set_online(uid,status):
    mysql_cursor.execute(
        "UPDATE users SET is_online = %s WHERE uid = %s",(status,uid)
    )
    mysql_conn.commit()

def get_user(uid):
    mysql_cursor.execute("SELECT * FROM users WHERE uid = %s",(uid,))
    return mysql_cursor.fetchone()