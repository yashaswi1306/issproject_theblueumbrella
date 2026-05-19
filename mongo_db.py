from pymongo import MongoClient
# from dotenv import load_dotenv
import os


mongo_client = MongoClient("mongodb://localhost:27017/")
mongo_db=mongo_client["arena_db"]
image_list=mongo_db["images"]


def upsert_image(uid,base64_img):
    image_list.update_one(
        {"uid":uid},
        {
            "$set":{"image":base64_img}
        },
        upsert=True
    )

def get_all():
    result={}

    for im in image_list.find():
        result[im["uid"]]=im["image"]

    return result