from flask import Flask, render_template, request, jsonify
from math import inf

app = Flask(__name__)

DIRS = [(-1,0),(0,1),(1,0),(0,-1)]  

def manhattan(a, b):
    return abs(a[0]-b[0]) + abs(a[1]-b[1])

def find_positions(grid, target):
    pos=[]
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            if grid[r][c] == target:
                pos.append((r,c))
    return pos

def risk_near_hazards(cell, hazards, radius=2):
    """
    Penalti risiko karena dekat bahaya (F).
    Jika jarak <= radius: penalti = 1/(d+1)
    Jika jarak > radius: 0
    """
    total = 0.0
    for hz in hazards:
        d = manhattan(cell, hz)
        if d <= radius:
            total += 1.0 / (d + 1.0)
    return total

def push_topk(arr, cand, k=10):
    arr.append(cand)
    arr.sort(key=lambda x: (x["score"], x["steps"]))
    if len(arr) > k:
        arr.pop()

def worst_score(arr, k=10):
    if len(arr) < k:
        return inf
    return arr[-1]["score"]

def find_top10_safe_paths(
    grid,
    top_k=10,
    w_len=1.0,
    w_risk=8.0,
    radius=2,
    allow_revisit=True,
    max_visit_per_cell=2,
    step_levels=(30, 45, 60, 80, 120, 160, 220),
    max_nodes=900000,
):
    """
    Backtracking (DFS + mundur) untuk mencari 10 jalur "paling aman".
    - F tidak boleh dilewati.
    - Risiko = penalti jika dekat F (radius).
    - Score = w_len*steps + w_risk*risk_sum
    - Agar bisa dapat 10 solusi, kita:
      (1) menaikkan max_steps bertahap
      (2) boleh revisit terbatas (maks 2x per sel) supaya ada variasi jalur
    """

    R = len(grid)
    C = len(grid[0]) if R else 0

    starts = find_positions(grid, "S")
    exits  = find_positions(grid, "E")
    hazards = find_positions(grid, "F")

    if not starts:
        return None, "Start (S) belum ada."
    if not exits:
        return None, "Exit (E) belum ada."

    start = starts[0]
    exit_pos = exits[0]  # 1 exit biar jelas

    def in_bounds(r,c):
        return 0 <= r < R and 0 <= c < C

    def walkable(r,c):
        # dinding dan bahaya tidak boleh diinjak
        if grid[r][c] == "#":
            return False
        if grid[r][c] == "F":
            return False
        return True

    def min_dist_to_exit(cell):
        return manhattan(cell, exit_pos)

    # hasil akhir
    solutions = []

    # hitung risk awal
    start_risk = risk_near_hazards(start, hazards, radius)

    # visit_count untuk mode revisit
    visit_count = {}
    visit_count[start] = 1

    nodes = 0

    def can_step(cell):
        if not allow_revisit:
            return cell not in visit_count
        return visit_count.get(cell, 0) < max_visit_per_cell

    def add_visit(cell):
        visit_count[cell] = visit_count.get(cell, 0) + 1

    def remove_visit(cell):
        visit_count[cell] -= 1
        if visit_count[cell] <= 0:
            del visit_count[cell]

    def dfs(r, c, path, risk_sum, max_steps):
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            return

        steps = len(path) - 1
        if steps > max_steps:
            return

        # sampai exit -> simpan
        if (r, c) == exit_pos:
            score = (w_len * steps) + (w_risk * risk_sum)
            push_topk(solutions, {
                "path": path[:],
                "steps": steps,
                "risk_sum": risk_sum,
                "score": score
            }, k=top_k)
            return

        # pruning: kalau sudah punya 10 solusi, hentikan cabang yang tidak mungkin lebih baik
        ws = worst_score(solutions, k=top_k)
        if ws < inf:
            optimistic_steps = steps + min_dist_to_exit((r, c))
            optimistic_score = (w_len * optimistic_steps) + (w_risk * risk_sum)
            if optimistic_score >= ws:
                return

        prev = path[-2] if len(path) >= 2 else None

        for dr, dc in DIRS:
            nr, nc = r + dr, c + dc
            nxt = (nr, nc)

            if not in_bounds(nr, nc):
                continue

            # boleh masuk exit walau bukan '.' (exit itu 'E')
            if nxt != exit_pos and not walkable(nr, nc):
                continue

            # cegah bolak-balik 2 langkah: A->B->A (biar variasi lebih “bermakna”)
            if prev is not None and nxt == prev:
                continue

            if not can_step(nxt):
                continue

            add_visit(nxt)
            path.append(nxt)

            added_risk = risk_near_hazards(nxt, hazards, radius)
            dfs(nr, nc, path, risk_sum + added_risk, max_steps)

            path.pop()
            remove_visit(nxt)

    # Jalankan bertahap: naikkan max_steps sampai dapat 10 solusi
    for max_steps in step_levels:
        if len(solutions) >= top_k:
            break
        dfs(start[0], start[1], [start], start_risk, max_steps)

        # kalau node sudah habis, stop
        if nodes > max_nodes:
            break

    if not solutions:
        return None, "Tidak ada jalur dari S ke E. Coba kurangi dinding (#)."

    # kalau masih kurang dari 10: biasanya map memang sempit sekali.
    # tapi dengan revisit terbatas biasanya tetap bisa 10 kalau ada minimal 1 jalur.
    return solutions, None


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/solve", methods=["POST"])
def solve():
    data = request.get_json(force=True)
    grid = data.get("grid")

    radius = int(data.get("radius", 2))
    w_risk = float(data.get("w_risk", 8.0))

    sols, err = find_top10_safe_paths(
        grid,
        top_k=10,
        w_len=1.0,
        w_risk=w_risk,
        radius=radius,
        allow_revisit=True,        # supaya dapat 10 solusi
        max_visit_per_cell=2,      # revisit maksimal 2x per sel
        step_levels=(30, 45, 60, 80, 120, 160, 220),
        max_nodes=900000
    )

    if err:
        return jsonify({"ok": False, "error": err})

    out = []
    for s in sols:
        out.append({
            "steps": s["steps"],
            "risk_sum": s["risk_sum"],
            "score": s["score"],
            "path": [[r,c] for (r,c) in s["path"]],
        })

    return jsonify({"ok": True, "solutions": out})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
