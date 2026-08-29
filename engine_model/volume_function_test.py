from math import pi, cos, radians, sin

# Using exact Rotax geometry from stage1_2_na_baseline.py
ROTAX_GEOMETRY = {
    "bore_m": 0.084,
    "stroke_m": 0.061,
    "compression_ratio": 8.2,
}

def swept_volume_per_cylinder(bore_m, stroke_m):
    return (pi/4.0) * bore_m**2 * stroke_m

def clearance_volume_from_cr(vd, cr):
    return vd/(cr-1.0)

def cyl_volume_at_theta(vd, vc, theta_deg):
    theta_rad = radians(theta_deg)
    return vc + 0.5 * vd * (1.0 - cos(theta_rad))

# compute
Vd = swept_volume_per_cylinder(ROTAX_GEOMETRY['bore_m'], ROTAX_GEOMETRY['stroke_m'])
Vc = clearance_volume_from_cr(Vd, ROTAX_GEOMETRY['compression_ratio'])

angles = list(range(0, 721))
vols = [cyl_volume_at_theta(Vd, Vc, th) for th in angles]

Vmin = min(vols)
Vmax = max(vols)
idx_min = vols.index(Vmin)
idx_max = vols.index(Vmax)
CR_eff = Vmax / Vmin

print(f"Vd (m3) = {Vd:.12g}, Vc (m3) = {Vc:.12g}")
print(f"Vd (cc) = {Vd*1e6:.6f}, Vc (cc) = {Vc*1e6:.6f}")
print(f"Vmin (cc) = {Vmin*1e6:.6f} at theta = {idx_min} deg")
print(f"Vmax (cc) = {Vmax*1e6:.6f} at theta = {idx_max} deg")
print(f"Effective CR = {CR_eff:.6f}")
print('\nSample values:')
for th in [0,90,180,270,360,450,540,630,720]:
    v = cyl_volume_at_theta(Vd, Vc, th)
    print(f" theta={th:3d} deg => V={v*1e6:.6f} cc")

# quick check expected
V_BDC = cyl_volume_at_theta(Vd, Vc, 180.0)
V_TDC = cyl_volume_at_theta(Vd, Vc, 0.0)
print('\nV_BDC (cc) =', V_BDC*1e6, 'V_TDC (cc)=', V_TDC*1e6)
print('Check V_BDC - (Vc+Vd) =', (V_BDC - (Vc+Vd))*1e6, 'cc')
