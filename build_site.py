"""
build_site.py — genera docs/index.html de La Pizarra con los datos más recientes.
Lo corre GitHub automáticamente (ver .github/workflows/actualizar.yml).
Para correrlo en tu compu: python3 build_site.py
"""
import nflreadpy as nfl, pandas as pd, numpy as np, json, os
S=nfl.get_current_season()
pbp=nfl.load_pbp(S).to_pandas(); pbp=pbp[pbp.season_type=="REG"]
ps=nfl.load_player_stats(S).to_pandas(); ps=ps[ps.season_type=="REG"]
sch=nfl.load_schedules(S).to_pandas(); sch=sch[(sch.game_type=="REG")]
rank=nfl.load_ff_rankings().to_pandas()
ids=nfl.load_ff_playerids().to_pandas()
wk=int(ps.week.max())
# names
names=ps.groupby('player_id').agg(n=('player_display_name','last'),pos=('position','last'),tm=('team','last')).reset_index()
def nm(df,col):
    return df.merge(names,left_on=col,right_on='player_id',how='left')
out={}
# QB
db=pbp[(pbp.qb_dropback==1)&pbp.passer_player_id.notna()]
qb=db.groupby('passer_player_id').agg(plays=('epa','size'),epa=('epa','mean'),cpoe=('cpoe','mean')).reset_index()
py=ps[ps.position=='QB'].groupby('player_id').agg(yds=('passing_yards','sum'),td=('passing_tds','sum'),int_=('passing_interceptions','sum'),att=('attempts','sum'),cmp=('completions','sum')).reset_index()
qb=nm(qb,'passer_player_id').merge(py,on='player_id',how='left')
qb=qb[(qb.plays>=30)&(qb.pos=='QB')]
qb['ypa']=qb.yds/qb.att
out['qb']=[dict(id=r.player_id,n=r.n,t=r.tm,plays=int(r.plays),epa=round(r.epa,3),cpoe=round(r.cpoe,1) if pd.notna(r.cpoe) else None,yds=int(r.yds),td=int(r.td),int=int(r.int_),ypa=round(r.ypa,1)) for r in qb.itertuples()]
# receivers
rec=ps[ps.position.isin(['WR','TE','RB'])].groupby('player_id').agg(rec=('receptions','sum'),tgt=('targets','sum'),yds=('receiving_yards','sum'),td=('receiving_tds','sum'),yac=('receiving_yards_after_catch','sum'),ts=('target_share','mean')).reset_index()
rec=rec.merge(names,on='player_id'); rec=rec[rec.tgt>=5]
rec['ypr']=rec.yds/rec.rec.replace(0,np.nan)
out['rec']=[dict(id=r.player_id,n=r.n,p=r.pos,t=r.tm,rec=int(r.rec),tgt=int(r.tgt),yds=int(r.yds),td=int(r.td),ypr=round(r.ypr,1) if pd.notna(r.ypr) else 0,ts=round(float(r.ts or 0),3)) for r in rec.itertuples()]
# rushers
ru=pbp[(pbp.rush_attempt==1)&pbp.rusher_player_id.notna()].groupby('rusher_player_id').agg(car=('epa','size'),epa=('epa','mean'),yds=('rushing_yards','sum'),td=('rush_touchdown','sum')).reset_index()
ru=nm(ru,'rusher_player_id'); ru=ru[(ru.car>=10)&(ru.pos.isin(['RB','QB','WR']))]
ru['ypc']=ru.yds/ru.car
out['rush']=[dict(id=r.player_id,n=r.n,p=r.pos,t=r.tm,car=int(r.car),yds=int(r.yds),td=int(r.td),ypc=round(r.ypc,1),epa=round(r.epa,3)) for r in ru.itertuples()]
# teams
g=sch.dropna(subset=['home_score'])
rows=[]
for r in g.itertuples():
    rows.append((r.home_team,r.away_team,r.home_score,r.away_score,r.week)); rows.append((r.away_team,r.home_team,r.away_score,r.home_score,r.week))
gm=pd.DataFrame(rows,columns=['tm','opp','pf','pa','wk'])
gm['w']=(gm.pf>gm.pa).astype(int); gm['l']=(gm.pf<gm.pa).astype(int); gm['tie']=(gm.pf==gm.pa).astype(int)
rec_t=gm.groupby('tm').agg(w=('w','sum'),l=('l','sum'),tie=('tie','sum'),pf=('pf','sum'),pa=('pa','sum')).reset_index()
rec_t['pct']=(rec_t.w+0.5*rec_t.tie)/(rec_t.w+rec_t.l+rec_t.tie)
winners=set(rec_t[rec_t.pct>0.5].tm)
gm['vsw']=gm.opp.isin(winners)
vw=gm[gm.vsw].groupby('tm').agg(vw_w=('w','sum'),vw_l=('l','sum')).reset_index()
off=pbp[pbp.play_type.isin(['pass','run'])].groupby('posteam').agg(off_epa=('epa','mean')).reset_index().rename(columns={'posteam':'tm'})
de=pbp[pbp.play_type.isin(['pass','run'])].groupby('defteam').agg(def_epa=('epa','mean')).reset_index().rename(columns={'defteam':'tm'})
sk=pbp[pbp.sack==1].groupby('defteam').size().rename('sacks').reset_index().rename(columns={'defteam':'tm'})
to=pbp.groupby('defteam').agg(ints=('interception','sum'),fum=('fumble_lost','sum')).reset_index().rename(columns={'defteam':'tm'})
T=rec_t.merge(vw,on='tm',how='left').merge(off,on='tm').merge(de,on='tm').merge(sk,on='tm',how='left').merge(to,on='tm',how='left').fillna(0)
out['teams']=[dict(t=r.tm,w=int(r.w),l=int(r.l),pf=int(r.pf),pa=int(r.pa),vw=f"{int(r.vw_w)}-{int(r.vw_l)}",vwg=int(r.vw_w+r.vw_l),vww=int(r.vw_w),oepa=round(r.off_epa,3),depa=round(r.def_epa,3),sacks=int(r.sacks),tko=int(r.ints+r.fum)) for r in T.itertuples()]
# fantasy: ownership + ECR value for all players via ros ppr pages
rr=rank[rank.page_type.isin(['redraft-qb','redraft-rb','redraft-wr','redraft-te'])]
ov=rank[rank.page_type=='redraft-overall'][['id','ecr']].rename(columns={'ecr':'ecr_ov'})
rr=rr.merge(ov,on='id',how='left')
mp=ids[['fantasypros_id','gsis_id']].dropna().copy(); mp['fantasypros_id']=mp.fantasypros_id.astype(int); mp=mp.drop_duplicates('fantasypros_id')
rr=rr.merge(mp,left_on='id',right_on='fantasypros_id',how='left')
# usage from player stats
u=ps[ps.position.isin(['QB','RB','WR','TE'])]
last=u[u.week==wk].set_index('player_id'); prev=u[u.week==wk-1].set_index('player_id')
sc=nfl.load_snap_counts(S).to_pandas(); mapp=ids[['pfr_id','gsis_id']].dropna()
sc=sc.merge(mapp,left_on='pfr_player_id',right_on='pfr_id').rename(columns={'gsis_id':'player_id'})
snl=sc[sc.week==wk].set_index('player_id').offense_pct; snp=sc[sc.week==wk-1].set_index('player_id').offense_pct
tot=u.groupby('player_id').agg(ppr=('fantasy_points_ppr','sum'),g=('week','nunique'))
fan=[]
for r in rr.drop_duplicates('id').itertuples():
    pid=r.gsis_id
    L=last.loc[pid] if isinstance(pid,str) and pid in last.index else None
    P=prev.loc[pid] if isinstance(pid,str) and pid in prev.index else None
    opp=lambda x: int((x.carries or 0)+(x.targets or 0)) if x is not None else 0
    fan.append(dict(g=pid if isinstance(pid,str) else None,n=r.player,p=r.pos,t=r.team,own=round(float(r.player_owned_avg),1) if pd.notna(r.player_owned_avg) else None,
        ecr=round(float(r.ecr_ov),1) if pd.notna(r.ecr_ov) else None, pr=round(float(r.ecr),1),
        ppg=round(float(tot.loc[pid].ppr/tot.loc[pid].g),1) if isinstance(pid,str) and pid in tot.index else None,
        opp=opp(L), opp0=opp(P),
        snap=round(float(snl.get(pid,np.nan)),2) if isinstance(pid,str) and pd.notna(snl.get(pid,np.nan)) else None,
        snap0=round(float(snp.get(pid,np.nan)),2) if isinstance(pid,str) and pd.notna(snp.get(pid,np.nan)) else None))
out['fantasy']=fan

# ---------- Extras: capturas, Next Gen Stats, drops, tendencias de equipo, defensa, Sleeper ----------
def rnd(v,d=1):
    return None if v is None or pd.isna(v) else round(float(v),d)
tot_p=ps.groupby('player_id').agg(sk=('sacks_suffered','sum'),sky=('sack_yards_lost','sum'))
ngp=nfl.load_nextgen_stats(stat_type='passing').to_pandas()
ngp=ngp[(ngp.season==S)&(ngp.week==0)].drop_duplicates('player_gsis_id').set_index('player_gsis_id')
for q in out['qb']:
    k=int(tot_p.sk.get(q['id'],0)); q['sk']=k; q['skr']=rnd(k/q['plays'],3) if q['plays'] else None
    q['ttt']=rnd(ngp.avg_time_to_throw.get(q['id'],np.nan),2); q['iay']=rnd(ngp.avg_intended_air_yards.get(q['id'],np.nan),1)
ngr=nfl.load_nextgen_stats(stat_type='receiving').to_pandas()
ngr=ngr[(ngr.season==S)&(ngr.week==0)].drop_duplicates('player_gsis_id').set_index('player_gsis_id')
try:
    adv=nfl.load_pfr_advstats(S,stat_type='rec').to_pandas()
    adv=adv.merge(ids[['pfr_id','gsis_id']].dropna(),left_on='pfr_player_id',right_on='pfr_id')
    drops=adv.groupby('gsis_id').receiving_drop.sum()
except Exception:
    drops=pd.Series(dtype=float)
for r in out['rec']:
    r['sep']=rnd(ngr.avg_separation.get(r['id'],np.nan),1)
    r['ays']=rnd(ngr.percent_share_of_intended_air_yards.get(r['id'],np.nan),1)
    r['yacx']=rnd(ngr.avg_yac_above_expectation.get(r['id'],np.nan),1)
    d=drops.get(r['id'],np.nan); r['drop']=None if pd.isna(d) else int(d)
pr=pbp[pbp.play_type.isin(['pass','run'])]
tend=pr.groupby('posteam').agg(pp=('pass_attempt','mean'),proe=('pass_oe','mean')).reset_index()
for t in out['teams']:
    x=tend[tend.posteam==t['t']]
    if len(x):
        t['pp']=rnd(x.pp.iloc[0],3); t['rp']=rnd(1-x.pp.iloc[0],3); t['proe']=rnd(x.proe.iloc[0],1)
DEF=['LB','CB','DT','SAF','DE','DB','OLB','FS','S','MLB','ILB','NT','DL','EDGE']
dfn=ps[ps.position.isin(DEF)].groupby('player_id').agg(n=('player_display_name','last'),p=('position','last'),t=('team','last'),
    solo=('def_tackles_solo','sum'),ast=('def_tackle_assists','sum'),tfl=('def_tackles_for_loss','sum'),sk=('def_sacks','sum'),
    qbh=('def_qb_hits','sum'),int_=('def_interceptions','sum'),pd_=('def_pass_defended','sum'),ff=('def_fumbles_forced','sum'),
    fr=('fumble_recovery_opp','sum'),td=('def_tds','sum')).reset_index()
dfn['tk']=dfn.solo+dfn.ast
dfn=dfn[(dfn.tk>=4)|(dfn.sk>0)|(dfn.int_>0)|(dfn.ff>0)|(dfn.fr>0)]
out['def']=[dict(id=r.player_id,n=r.n,p=r.p,t=r.t,tk=int(r.tk),solo=int(r.solo),tfl=rnd(r.tfl,1),sk=rnd(r.sk,1),qbh=int(r.qbh),int=int(r.int_),pd=int(r.pd_),ff=int(r.ff),fr=int(r.fr),td=int(r.td)) for r in dfn.itertuples()]
sl=ids[ids.sleeper_id.notna()&ids.position.isin(['QB','RB','WR','TE','K'])].copy()
sl['sid']=sl.sleeper_id.astype(int).astype(str)
sl=sl.drop_duplicates('sid')
out['sleeper']={r.sid:[r.name,r.position,r.team if isinstance(r.team,str) else '',r.gsis_id if isinstance(r.gsis_id,str) else ''] for r in sl.itertuples()}
out['season']=int(S)
heads=ps.groupby('player_id').headshot_url.last()
for lst in ('qb','rec','rush','def'):
    for r in out[lst]:
        h=heads.get(r['id']); r['img']=h if isinstance(h,str) else None
lg=nfl.load_teams().to_pandas().team_league_logo.dropna()
out['nfl_logo']=lg.iloc[0] if len(lg) else None

# ---------- Partidos de la semana (NFL) ----------
from zoneinfo import ZoneInfo
from datetime import datetime
COORD={"ATL97":(33.7554,-84.4008),"BAL00":(39.2780,-76.6227),"BOS00":(42.0909,-71.2643),"BUF00":(42.7738,-78.7870),"CAR00":(35.2258,-80.8528),
"CHI98":(41.8623,-87.6167),"CIN00":(39.0955,-84.5161),"CLE00":(41.5061,-81.6995),"DAL00":(32.7473,-97.0945),"DEN00":(39.7439,-105.0201),
"DET00":(42.3400,-83.0456),"GNB00":(44.5013,-88.0622),"HOU00":(29.6847,-95.4107),"IND00":(39.7601,-86.1639),"JAX00":(30.3239,-81.6373),
"KAN00":(39.0489,-94.4839),"LAX01":(33.9535,-118.3392),"LON00":(51.5560,-0.2796),"LON02":(51.6043,-0.0664),"MAD01":(40.4531,-3.6883),
"MEL00":(-37.8200,144.9834),"MEX00":(19.3029,-99.1505),"MIA00":(25.9580,-80.2389),"MIN01":(44.9737,-93.2575),"MUN01":(48.2188,11.6247),
"NAS00":(36.1665,-86.7713),"NOR00":(29.9511,-90.0812),"NYC01":(40.8135,-74.0745),"PAR00":(48.9245,2.3602),"PHI00":(39.9008,-75.1675),
"PHO00":(33.5276,-112.2626),"PIT00":(40.4468,-80.0158),"RIO00":(-22.9121,-43.2302),"SEA00":(47.5952,-122.3316),"SFO01":(37.4030,-121.9700),
"TAM00":(27.9759,-82.5033),"VEG00":(36.0909,-115.1833),"WAS00":(38.9078,-76.8645)}
BYNAME={"Tottenham Hotspur Stadium":"LON02","Wembley Stadium":"LON00"}
OPEN_AIR={"MUN01","PAR00","MEL00"}  # el dato de techo viene mal para estos estadios
teams=nfl.load_teams().to_pandas().set_index('team_abbr')
full=nfl.load_schedules(S).to_pandas(); full=full[full.game_type=='REG']
pend=full[full.home_score.isna()]
gw=int(pend.week.min()) if len(pend) else int(full.week.max())
ET=ZoneInfo("America/New_York")
def team_info(a):
    if a in teams.index:
        t=teams.loc[a]; return dict(a=a,n=t.team_nick,c=t.team_color,logo=t.team_logo_espn)
    return dict(a=a,n=a,c="#555",logo="")
gl=[]
for r in full[full.week==gw].sort_values(['gameday','gametime']).itertuples():
    try:
        ko=datetime.strptime(f"{r.gameday} {r.gametime}","%Y-%m-%d %H:%M").replace(tzinfo=ET).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%MZ")
    except Exception:
        ko=None
    sid=r.stadium_id if isinstance(r.stadium_id,str) and r.stadium_id else BYNAME.get(r.stadium)
    roof=r.roof if isinstance(r.roof,str) else None
    if sid in OPEN_AIR: roof="outdoors"
    ll=COORD.get(sid)
    gl.append(dict(ko=ko,away=team_info(r.away_team),home=team_info(r.home_team),stadium=r.stadium,roof=roof,
        lat=ll[0] if ll else None,lon=ll[1] if ll else None,
        aml=rnd(r.away_moneyline,0),hml=rnd(r.home_moneyline,0),spread=rnd(r.spread_line,1),total=rnd(r.total_line,1),
        as_=None if pd.isna(r.away_score) else int(r.away_score),hs=None if pd.isna(r.home_score) else int(r.home_score)))
out['games']=gl; out['gweek']=gw

# ---------- Liga MX: estadísticas de jugadores partido por partido (ESPN) ----------
import urllib.request
from datetime import date, timedelta
def espn(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (La Pizarra)"})
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))
def mx_player_stats():
    base="https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1"
    hoy=date.today().isoformat()
    base_sb=espn(f"{base}/scoreboard")
    lg=(base_sb.get("leagues") or [{}])[0]
    out['mx_logo']=((lg.get("logos") or [{}])[0]).get("href")
    cal=[(x if isinstance(x,str) else (x.get("startDate") or x.get("value") or ""))[:10] for x in lg.get("calendar",[])]
    fechas=[d for d in cal if d and d<=hoy]
    print(f"Liga MX: {len(fechas)} fechas jugadas en el calendario del torneo")
    eventos={}
    for d in fechas:   # ESPN organiza la Liga MX por día
        try:
            j=espn(f"{base}/scoreboard?dates={d.replace('-','')}")
            for e in j.get("events",[]):
                if e.get("status",{}).get("type",{}).get("state")=="post": eventos[e["id"]]=e
        except Exception as ex:
            print("  aviso fecha",d,ex)
    P={}
    def fila(pid,nombre,equipo,equipo_n,pos):
        if pid not in P: P[pid]=dict(n=nombre,t=equipo,tn=equipo_n,pos=pos,ap=0,g=0,as_=0,sh=None,sot=None,yc=0,rc=0,fc=None,fs=None,sv=None,gc=None)
        return P[pid]
    def suma(r,k,v):
        if v is None: return
        r[k]=(r[k] or 0)+v
    fuente="resumen"
    con_stats=0
    for eid,e in list(eventos.items()):
        if eid=="_diag": continue
        comp=(e.get("competitions") or [{}])[0]
        equipos={c["team"]["id"]:(c["team"].get("abbreviation",""),c["team"].get("displayName","")) for c in comp.get("competitors",[]) if "team" in c}
        usado=False
        try:
            sm=espn(f"{base}/summary?event={eid}")
            if not eventos.get("_diag"):
                eventos["_diag"]=True
                ros=sm.get("rosters") or []
                ej=((ros[0].get("roster") or [{}])[0].get("stats") or []) if ros else []
                print("  diagnóstico resumen: claves",list(sm.keys())[:15],"| rosters:",len(ros),"| stats ejemplo:",[x.get("name") for x in ej][:12])
            for ros in sm.get("rosters",[]):
                tid=str(ros.get("team",{}).get("id",""))
                ab,tn=equipos.get(tid,(ros.get("team",{}).get("abbreviation",""),ros.get("team",{}).get("displayName","")))
                for p in ros.get("roster",[]):
                    a=p.get("athlete",{})
                    st={x.get("name"):x.get("value") for x in p.get("stats",[]) if isinstance(x,dict)}
                    jugo=p.get("starter") or p.get("subbedIn") or (st.get("appearances") or 0)>0
                    if not st and not jugo: continue
                    r=fila(a.get("id"),a.get("displayName"),ab,tn,(p.get("position") or {}).get("abbreviation",""))
                    if jugo: r["ap"]+=1
                    def v(*ks):
                        for k in ks:
                            if st.get(k) is not None:
                                try: return float(st[k])
                                except Exception: pass
                        return None
                    suma(r,"g",v("totalGoals","goals")); suma(r,"as_",v("goalAssists","assists"))
                    suma(r,"sh",v("totalShots","shots")); suma(r,"sot",v("shotsOnTarget"))
                    suma(r,"yc",v("yellowCards")); suma(r,"rc",v("redCards"))
                    suma(r,"fc",v("foulsCommitted")); suma(r,"fs",v("foulsSuffered"))
                    suma(r,"sv",v("saves")); suma(r,"gc",v("goalsConceded"))
                    if st: usado=True
        except Exception as ex:
            print("  aviso resumen",eid,ex)
        if usado: con_stats+=1; continue
        # Respaldo: goles y tarjetas desde los eventos del marcador
        fuente="eventos"
        for det in comp.get("details",[]):
            tipo=(det.get("type") or {}).get("text","").lower()
            for a in det.get("athletesInvolved",[])[:1]:
                tid=str((a.get("team") or det.get("team") or {}).get("id",""))
                ab,tn=equipos.get(tid,("",""))
                r=fila(a.get("id"),a.get("displayName"),ab,tn,(a.get("position") or {}).get("abbreviation","") if isinstance(a.get("position"),dict) else "")
                if det.get("scoringPlay") and not det.get("ownGoal"): r["g"]+=1
                elif det.get("redCard") or "red" in tipo: r["rc"]+=1
                elif det.get("yellowCard") or "yellow" in tipo: r["yc"]+=1
    filas=[]
    for pid,r in P.items():
        if not r["n"]: continue
        pg=(r["pos"] or "M")[0].upper(); pg=pg if pg in "GDMF" else "M"
        filas.append(dict(id=pid,n=r["n"],t=r["t"],tn=r["tn"],pos=r["pos"],pg=pg,ap=r["ap"] or None,g=int(r["g"]),**{"as":int(r["as_"])},
            sh=r["sh"],sot=r["sot"],yc=int(r["yc"]),rc=int(r["rc"]),fc=r["fc"],fs=r["fs"],sv=r["sv"],gc=r["gc"]))
    eventos.pop("_diag",None)
    print(f"Liga MX: {len(eventos)} partidos terminados, {con_stats} con estadísticas por jugador, {len(filas)} jugadores")
    return filas
try:
    out['mxp']=mx_player_stats()
except Exception as ex:
    print("Liga MX: no se pudieron obtener estadísticas de jugadores:",ex); out['mxp']=[]
out['week']=wk; out['winners']=sorted(winners)
data=json.dumps(out,ensure_ascii=False,allow_nan=False)
aqui=os.path.dirname(os.path.abspath(__file__))
notas=json.load(open(os.path.join(aqui,'notas.json'),encoding='utf-8'))
notas_js=json.dumps([[n['jugador'],n['posicion'],n['equipo'],n['texto']] for n in notas['notas']],ensure_ascii=False)
html=open(os.path.join(aqui,'template.html'),encoding='utf-8').read().replace('__DATA__',data).replace('__NOTES__',notas_js)
os.makedirs(os.path.join(aqui,'docs'),exist_ok=True)
open(os.path.join(aqui,'docs','index.html'),'w',encoding='utf-8').write(html)
print(f'Listo: docs/index.html (temporada {S}, semana {wk})')
