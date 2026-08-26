import re
from collections import defaultdict
import earthaccess

auth = earthaccess.login(strategy="netrc")

# Mt. Rainier, to line up with the existing nisar/ notebooks
BBOX = (-121.932, 46.754, -121.5707, 46.964)

for short_name in ("NISAR_L2_GCOV_PROVISIONAL_V1", "NISAR_L2_GCOV_BETA_V1"):
    res = earthaccess.search_data(short_name=short_name, bounding_box=BBOX, count=200)
    print(f"\n=== {short_name}: {len(res)} granules")
    # NISAR_L2_PR_GCOV_{cycle}_{absorbit}_{dir}_{relorbit}_{frame}_{pols}_..._{start}_{end}_{CRID}...
    rx = re.compile(
        r"NISAR_L2_\w\w_GCOV_(\d+)_(\d+)_([AD])_(\d+)_(\d+)_(\w+)_\w_"
        r"(\d{8}T\d{6})_(\d{8}T\d{6})_(\w+)_"
    )
    groups = defaultdict(list)
    for g in res:
        links = [u for u in g.data_links(access="direct") if u.endswith(".h5")]
        if not links:
            continue
        url = links[0]
        m = rx.search(url.rsplit("/", 1)[-1])
        if not m:
            continue
        _, _, direction, relorb, frame, pols, start, _, crid = m.groups()
        groups[(direction, relorb, frame, pols)].append((start, crid, url))

    for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        dates = sorted({i[0][:8] for i in items})
        print(f"  dir={key[0]} relorb={key[1]} frame={key[2]} pols={key[3]}: "
              f"{len(items)} granules, {len(dates)} dates {dates[:6]}")
        for it in sorted(items)[:3]:
            print("     ", it[0], it[1], it[2].rsplit('/', 1)[-1][:60])
