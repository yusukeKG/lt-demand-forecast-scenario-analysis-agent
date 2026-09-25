import os, numpy as np, pandas as pd
from features import build_features, FEATURES
BASE=os.path.dirname(os.path.abspath(__file__)); o=os.path.join(BASE,"data")+"/"; D=o
master=pd.read_csv(o+"01_country_master.csv")
hist=pd.read_csv(o+"02_drivers_country_year.csv")
dem=pd.read_csv(o+"04_demand_dummy_country_year.csv")
fut=pd.read_csv(o+"08_future_drivers_country_year_scenario.csv")
base_cols=["iso3","year","population","urban_pct","gdp_pc_ppp_const2021","gdp_growth_pct","gfcf_pct_gdp","coal_prod_twh",
           "copper_usd_t_real2010","ironore_usd_dmtu_real2010","coal_aus_usd_t_real2010","gold_usd_oz_real2010"]
# 1990-94年の価格が無いと1995年のラグが欠損するが、DataRobotは欠損を扱えるのでそのまま
hf=build_features(hist[base_cols], master)
CAT={"一般建機":"general","ミニショベル":"mini","鉱山機械":"mining"}
ID=["iso3","year","population"]
for cat,slug in CAT.items():
    t=dem[dem.category==cat][["iso3","year","units"]].merge(hf,on=["iso3","year"])
    t["units_per_mn_pop"]=t.units/(t.population/1e6)
    t["partition"]=np.where(t.year<=2015,"train",np.where(t.year<=2020,"validation","holdout"))
    t["weight"]=np.sqrt(t.population/1e6)
    cols=ID+FEATURES+["partition","weight","units","units_per_mn_pop"]
    t[cols].round(5).to_csv(f"{D}train_{slug}.csv",index=False,encoding="utf-8-sig")
    bt=t[t.year<=2005].copy(); bt["partition"]=np.where(bt.year<=2002,"train","validation")
    bt[cols].round(5).to_csv(f"{D}backtest_train_{slug}_1995_2005.csv",index=False,encoding="utf-8-sig")
    t[t.year>=2006][cols].drop(columns=["partition","weight","units","units_per_mn_pop"]).round(5).to_csv(f"{D}backtest_score_{slug}_2006_2025.csv",index=False,encoding="utf-8-sig")
    isos=t.iso3.unique()
    # 予測用: 2021-2025年の実績を前につなげてラグを計算し、2026-2050年だけ残す
    parts=[]
    for scn in fut.scenario_id.unique():
        f=fut[(fut.scenario_id==scn)&fut.iso3.isin(isos)][base_cols]
        h=hist[hist.iso3.isin(isos)&(hist.year>=2019)][base_cols]
        x=build_features(pd.concat([h,f]),master); x=x[x.year>=2026]; x["scenario_id"]=scn; parts.append(x)
    s=pd.concat(parts); s["date"]=s.year.astype(str)+"-01-01"
    s[["scenario_id"]+ID+FEATURES].round(5).to_csv(f"{D}score_{slug}_2026_2050_all_scenarios.csv",index=False,encoding="utf-8-sig")
    print(slug, t.shape, s.shape, s[FEATURES].isna().sum().sum())
