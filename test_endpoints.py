import httpx

endpoints = [
    "/", "/app", "/plot-details", "/viewer",
    "/urbanscribe", "/layout-planner", "/login",
    "/api/config", "/api/plots",
    "/api/site-plan/zoning-rules/residential",
    "/api/layout-planner/strategies",
    "/interior-layout",
]

for e in endpoints:
    try:
        r = httpx.get("http://127.0.0.1:8000" + e, timeout=5)
        print(f"{e}: {r.status_code}")
    except Exception as ex:
        print(f"{e}: ERROR - {ex}")
