import tetra3, pathlib, time
t0 = time.time()
t3 = tetra3.Tetra3(load_database=None)
out = pathlib.Path.home() / "forge/skyfix/data/stars/phone_fov70_db"
try:
    t3.generate_database(max_fov=70, min_fov=20, star_catalog="hip_main", save_as=str(out), star_max_magnitude=7, verification_stars_per_fov=30)
except TypeError as e:
    print("retry with minimal args:", e)
    t3.generate_database(max_fov=70, star_catalog="hip_main", save_as=str(out))
print("DB saved to", out, "in", round(time.time()-t0), "s")
