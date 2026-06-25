[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/rd3t__9M)
# Introduction to Software Systems S26 
## Course Project: Identity-Verified Multiplayer Arena



The assignment is available [here](https://cs6201.github.io/s26/assets/Project.pdf).

[This](https://hackmd.io/@iss-spring-2026/S1WBWzzoWe) is where you can ask questions about it, for which you will receive answers [here](https://hackmd.io/@iss-spring-2026/ryZ_WGzibx).

Good luck, have fun!

# Project: The Blue Umbrella
CS6.201 ISS S26 : Identity-Verified Multiplayer Arena

Log in with your face, challenge classmates to Tic-Tac-Toe.

---

## Setup

### 1. Install dependencies
```bash
uv sync
```

### 2. Create a `.env` file
```
MYSQL_PASSWORD=your_password
MONGO_URI=mongodb://localhost:27017/
```

### 3. Set up MySQL
```bash
mysql -u root
```
```sql
CREATE DATABASE arena_db;
USE arena_db;
CREATE TABLE users (
    uid VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255),
    elo_rating INT DEFAULT 1200,
    is_online BOOLEAN DEFAULT FALSE
);
EXIT;
```

### 4. Run the scraper
```bash
uv run scraper.py
```

### 5. Start the server
```bash
uv run uvicorn main:app --reload
```

### 6. Open in browser
```
http://localhost:8000
```

---

## Assumptions
- Each student has a profile image hosted at `<website_url>/images/pfp.jpg`
- MySQL and MongoDB are both running locally
- Face recognition threshold is 0.7 (lower = stricter)

---

