import io, os, shutil

def patch(path, edits, backup=True):
    with io.open(path, encoding="utf-8") as fh:
        t = fh.read().replace("\r\n", "\n")
    orig = t
    for name, old, new in edits:
        if old not in t:
            print("  MISS %s" % name); return False
        t = t.replace(old, new, 1)
        print("  OK   %s" % name)
    if backup and not os.path.exists(path + ".perfbak"):
        shutil.copyfile(path, path + ".perfbak")
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(t)
    return t != orig

E = "engine_model/stage1_3_hybrid_engine_output.py"
print(E)
ok = patch(E, [
 ("vector interpolator",
  """        self._linear_interp = {
            col: LinearNDInterpolator(points_norm, self._df_model[col].to_numpy())
            for col in OUTPUT_COLUMNS
        }""",
  """        self._linear_interp = {
            col: LinearNDInterpolator(points_norm, self._df_model[col].to_numpy())
            for col in OUTPUT_COLUMNS
        }

        # One interpolator over all output columns at once. Four scalar
        # interpolators searched the same Delaunay triangulation four times per
        # point; this searches it once and returns the whole row.
        self._linear_interp_vec = LinearNDInterpolator(
            points_norm,
            self._df_model[OUTPUT_COLUMNS].to_numpy(dtype=float),
        )

        # Cached raw coordinate arrays for the exact-row test, so that path
        # stops going through pandas indexing on every query.
        self._exact_rpm = self.df["rpm"].to_numpy(dtype=float)
        self._exact_thr = self.df["throttle_pct"].to_numpy(dtype=float)
        self._exact_alt = self.df["alt_ft"].to_numpy(dtype=float)
        self._exact_tamb = self.df["t_amb_C"].to_numpy(dtype=float)
        self._query_cache = {}"""),

 ("exact-row fast path",
  """        exact_rows = self.find_exact_rows(
            rpm=rpm,
            throttle_pct=throttle_pct,
            altitude_ft=altitude_ft,
            ambient_temp_C=ambient_temp_C,
        )
        if len(exact_rows) > 0:
            row = exact_rows.iloc[0]""",
  """        exact_index = self._find_exact_index(
            rpm, throttle_pct, altitude_ft, ambient_temp_C
        )
        if exact_index is not None:
            row = self.df.iloc[exact_index]"""),

 ("single simplex search",
  """        point_norm = self._point_norm(rpm, throttle_pct, altitude_ft, ambient_temp_C)
        in_hull = bool(self._hull.find_simplex(point_norm)[0] >= 0)
        if not in_hull:""",
  """        point_norm = self._point_norm(rpm, throttle_pct, altitude_ft, ambient_temp_C)

        # A point outside the convex hull interpolates to NaN, which is exactly
        # the condition the separate find_simplex call used to test for. Reading
        # it off the interpolation result removes a second simplex search.
        interp_row = np.asarray(self._linear_interp_vec(point_norm)).ravel()

        if not np.all(np.isfinite(interp_row)):"""),

 ("use vector result",
  """            interpolated = True
        else:
            values = {}
            interpolated = False

            for col in OUTPUT_COLUMNS:
                interp_value = self._linear_interp[col](point_norm)
                value = float(np.asarray(interp_value).ravel()[0])
                if np.isfinite(value):
                    values[col] = value
                    interpolated = True
                else:
                    raise ValueError(
                        f"Linear interpolation failed for {col} at the calibrated "
                        "CSV operating point."
                    )""",
  """            interpolated = True
        else:
            values = {
                col: float(interp_row[index])
                for index, col in enumerate(OUTPUT_COLUMNS)
            }
            interpolated = True"""),

 ("no DataFrame copy in fallback",
  "        df = self._df_model.copy()\n",
  "        df = self._df_model\n"),

 ("rename query",
  """    def query(
        self,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float | None = None,
        *,
        mode: Literal["production", "validation", "boundary"] = "production",
    ) -> EngineOutputResult:""",
  """    def _find_exact_index(
        self,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float,
    ) -> int | None:
        \"\"\"Index of an exact grid row, or None. Same tolerance as before.\"\"\"
        mask = (
            np.isclose(self._exact_rpm, rpm)
            & np.isclose(self._exact_thr, throttle_pct)
            & np.isclose(self._exact_alt, altitude_ft)
            & np.isclose(self._exact_tamb, ambient_temp_C)
        )
        hits = np.flatnonzero(mask)
        return int(hits[0]) if hits.size else None

    def query(
        self,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float | None = None,
        *,
        mode: Literal["production", "validation", "boundary"] = "production",
    ) -> EngineOutputResult:
        \"\"\"Cached wrapper. Steady phases repeat the same point every second.\"\"\"
        key = (
            float(rpm),
            float(throttle_pct),
            float(altitude_ft),
            None if ambient_temp_C is None else float(ambient_temp_C),
            mode,
        )
        hit = self._query_cache.get(key)
        if hit is not None:
            return hit
        result = self._query_uncached(
            rpm, throttle_pct, altitude_ft, ambient_temp_C, mode=mode
        )
        if len(self._query_cache) < 200000:
            self._query_cache[key] = result
        return result

    def _query_uncached(
        self,
        rpm: float,
        throttle_pct: float,
        altitude_ft: float,
        ambient_temp_C: float | None = None,
        *,
        mode: Literal["production", "validation", "boundary"] = "production",
    ) -> EngineOutputResult:"""),
])
if not ok:
    raise SystemExit("engine patch failed, nothing written")

SHARED = '''_SHARED_ENGINE_MODEL = None


def _shared_engine_model():
    """One engine model for the whole run. The constructor builds a Delaunay
    triangulation of the full performance map, which cost 2.4 s per mission
    when every mission built its own."""
    global _SHARED_ENGINE_MODEL
    if _SHARED_ENGINE_MODEL is None:
        from engine_model.stage1_3_hybrid_engine_output import (
            Stage13HybridEngineOutput,
        )

        _SHARED_ENGINE_MODEL = Stage13HybridEngineOutput()
    return _SHARED_ENGINE_MODEL


'''

print("\ngenerate_stage6_normal_dataset.py")
patch("generate_stage6_normal_dataset.py", [
 ("shared model helper", "MISSION_TYPES = (", SHARED + "MISSION_TYPES = ("),
 ("pass shared model",
  """                    rows = run_mission_realistic(
                        config,
                        engine_seed=engine_number,
                    )""",
  """                    rows = run_mission_realistic(
                        config,
                        engine_seed=engine_number,
                        engine_model=_shared_engine_model(),
                    )"""),
])

print("\ngenerate_stage7_abnormal_dataset.py")
patch("generate_stage7_abnormal_dataset.py", [
 ("shared model helper", "DRIFT_CHANNELS = (", SHARED + "DRIFT_CHANNELS = ("),
 ("pass shared model",
  "healthy_rows = run_mission_realistic(config, engine_seed=engine_number)",
  "healthy_rows = run_mission_realistic(\n                                config,\n                                engine_seed=engine_number,\n                                engine_model=_shared_engine_model(),\n                            )"),
])
