"""Idempotent seed step: loads movies.csv + ratings_sample.csv into Redis.
Run once before the app server starts. Skips work if data is already present,
so a plain app-container restart (Redis untouched) stays fast.
"""
import csv
import os
import time
from collections import defaultdict

import redis

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
DATA_DIR = os.environ.get("DATA_DIR", "/data")


def wait_for_redis(r, timeout=30):
    start = time.time()
    while True:
        try:
            r.ping()
            return
        except redis.exceptions.ConnectionError:
            if time.time() - start > timeout:
                raise
            time.sleep(0.5)


def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    wait_for_redis(r)

    if r.get("seed:done"):
        print("seed already present, skipping load")
        return

    t0 = time.time()

    ratings_sum = defaultdict(float)
    ratings_count = defaultdict(int)
    with open(os.path.join(DATA_DIR, "ratings_sample.csv")) as f:
        for row in csv.DictReader(f):
            mid = row["movieId"]
            ratings_sum[mid] += float(row["rating"])
            ratings_count[mid] += 1

    movie_ids = []
    pipe = r.pipeline(transaction=False)
    with open(os.path.join(DATA_DIR, "movies.csv")) as f:
        for i, row in enumerate(csv.DictReader(f)):
            mid = row["movieId"]
            n = ratings_count.get(mid, 0)
            avg = (ratings_sum[mid] / n) if n else 0.0
            pipe.hset(f"movie:{mid}", mapping={
                "title": row["title"],
                "genres": row["genres"],
                "avg_rating": avg,
                "num_ratings": n,
            })
            movie_ids.append(mid)
            if i % 2000 == 0:
                pipe.execute()
    pipe.execute()

    r.sadd("all_movie_ids", *movie_ids)
    r.set("seed:done", "1")

    print(f"seeded {len(movie_ids)} movies in {time.time() - t0:.2f}s")


if __name__ == "__main__":
    main()
