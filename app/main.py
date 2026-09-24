import os
import socket
import time

from flask import Flask, jsonify, request, redirect, send_from_directory
import redis

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = Flask(__name__)
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)


@app.get("/")
def home():
    return redirect("/help.html")


@app.get("/help.html")
def help_page():
    return send_from_directory(STATIC_DIR, "help.html")

_search_index = None  # lazily built in-memory (movie_id, title_lower) list for substring search


def _build_search_index():
    global _search_index
    if _search_index is not None:
        return _search_index
    index = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, match="movie:*", count=1000)
        if keys:
            pipe = r.pipeline(transaction=False)
            for k in keys:
                pipe.hget(k, "title")
            titles = pipe.execute()
            for k, title in zip(keys, titles):
                if title:
                    index.append((k.split(":", 1)[1], title))
        if cursor == 0:
            break
    _search_index = index
    return index


@app.get("/health")
def health():
    try:
        r.ping()
    except redis.exceptions.ConnectionError:
        return jsonify({"status": "unhealthy", "reason": "redis unreachable"}), 503
    return jsonify({"status": "ok", "host": socket.gethostname()})


@app.get("/stats")
def stats():
    n_movies = r.scard("all_movie_ids")
    return jsonify({"movies_loaded": n_movies, "host": socket.gethostname()})


@app.get("/movies/search")
def search():
    q = request.args.get("q", "").strip().lower()
    limit = min(int(request.args.get("limit", 20)), 100)
    if not q:
        return jsonify({"results": []})
    index = _build_search_index()
    matches = [{"movie_id": mid, "title": title} for mid, title in index if q in title.lower()]
    return jsonify({"results": matches[:limit], "count": len(matches)})


@app.get("/movies/<movie_id>")
def get_movie(movie_id):
    data = r.hgetall(f"movie:{movie_id}")
    if not data:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "movie_id": movie_id,
        "title": data.get("title"),
        "genres": data.get("genres", "").split("|") if data.get("genres") else [],
        "avg_rating": float(data.get("avg_rating", 0)),
        "num_ratings": int(data.get("num_ratings", 0)),
        "served_by": socket.gethostname(),
    })


@app.post("/movies/<movie_id>/rate")
def rate_movie(movie_id):
    body = request.get_json(silent=True) or {}
    try:
        rating = float(body.get("rating"))
    except (TypeError, ValueError):
        return jsonify({"error": "rating (float) required"}), 400
    if not (0.5 <= rating <= 5.0):
        return jsonify({"error": "rating must be between 0.5 and 5.0"}), 400

    key = f"movie:{movie_id}"
    if not r.exists(key):
        return jsonify({"error": "not found"}), 404

    # Atomic-ish read-modify-write of the running average via a small Lua script.
    lua = """
    local key = KEYS[1]
    local new_rating = tonumber(ARGV[1])
    local n = tonumber(redis.call('HGET', key, 'num_ratings') or '0')
    local avg = tonumber(redis.call('HGET', key, 'avg_rating') or '0')
    local new_n = n + 1
    local new_avg = (avg * n + new_rating) / new_n
    redis.call('HSET', key, 'num_ratings', new_n, 'avg_rating', new_avg)
    return {tostring(new_n), tostring(new_avg)}
    """
    new_n, new_avg = r.eval(lua, 1, key, rating)
    return jsonify({"movie_id": movie_id, "num_ratings": int(new_n), "avg_rating": float(new_avg)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
