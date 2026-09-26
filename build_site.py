"""
build_site.py — genera docs/index.html de La Pizarra con los datos más recientes.
Lo corre GitHub automáticamente (ver .github/workflows/actualizar.yml).
Para correrlo en tu compu: python3 build_site.py
"""
import nflreadpy as nfl, pandas as pd, numpy as np, json, os
S=nfl.get_current_season()
pbp=nfl.load_pbp(S).to_pandas(); pbp=pbp[pbp.season_type=="REG"]
ps=nfl.load_player_stats(S).to_pandas(); ps=ps[ps.season_type=="REG"]
schAll=nfl.load_schedules(S).to_pandas()
sch=schAll[(schAll.game_type=="REG")]
# Postemporada real (vacío casi toda la temporada; se llena solo cuando empiezan los playoffs)
POST_LBL={"WC":"Ronda de comodines","DIV":"Ronda divisional","CON":"Campeonato de conferencia","SB":"Super Bowl"}
post=schAll[schAll.game_type!="REG"].sort_values("gameday")
rank=nfl.load_ff_rankings().to_pandas()
ids=nfl.load_ff_playerids().to_pandas()
wk=int(ps.week.max())
# names
names=ps.groupby('player_id').agg(n=('player_display_name','last'),pos=('position','last'),tm=('team','last')).reset_index()
def nm(df,col):
    return df.merge(names,left_on=col,right_on='player_id',how='left')
out={}
out['nfl_post']=[dict(round=POST_LBL.get(r.game_type,r.game_type),home=r.home_team,away=r.away_team,
    hs=int(r.home_score) if pd.notna(r.home_score) else None,as_=int(r.away_score) if pd.notna(r.away_score) else None,
    date=str(r.gameday)) for r in post.itertuples()]

# ---------- Palmarés histórico: campeonatos de liga por equipo ----------
# Datos fijos (no se pueden traer en vivo de ESPN): tomados y cruzados de Wikipedia
# ("List of Mexican/English/Spanish/Italian/German/French football champions",
# "List of Super Bowl champions"), sep 2026. Solo títulos de LIGA (no copas ni torneos
# internacionales). Se actualiza a mano cuando corresponda: al final de cada temporada.
PALMARES = {
  "nfl": [("Patriots",6),("Steelers",6),("49ers",5),("Cowboys",5),("Packers",4),("Giants",4),
    ("Chiefs",4),("Broncos",3),("Raiders",3),("Commanders",3),("Dolphins",2),("Ravens",2),
    ("Colts",2),("Rams",2),("Eagles",2),("Buccaneers",2),("Seahawks",2),("Bears",1),
    ("Jets",1),("Saints",1)],
  "mx": [("América",16),("Guadalajara",12),("Toluca",12),("Cruz Azul",10),("Tigres UANL",8),
    ("León",8),("Pumas UNAM",7),("Pachuca",7),("Santos Laguna",6),("Monterrey",5),
    ("Atlante",3),("Atlas",3),("Necaxa",3),("Puebla",2),("Zacatepec",2),("Veracruz",2),
    ("Tijuana",1),("Morelia",1),("Tecos",1),("Oro",1),("Tampico",1),("Marte",1),
    ("Asturias",1),("Real España",1)],
  "eng": [("Liverpool",20),("Manchester United",20),("Arsenal",14),("Manchester City",10),
    ("Everton",9),("Aston Villa",7),("Sunderland",6),("Chelsea",6),("Sheffield Wednesday",4),
    ("Newcastle United",4),("Blackburn Rovers",3),("Huddersfield Town",3),("Wolverhampton Wanderers",3),
    ("Leeds United",3),("Preston North End",2),("Burnley",2),("Portsmouth",2),("Tottenham Hotspur",2),
    ("Derby County",2),("Sheffield United",1),("West Bromwich Albion",1),("Ipswich Town",1),
    ("Nottingham Forest",1),("Leicester City",1)],
  "esp": [("Real Madrid",36),("Barcelona",29),("Atlético Madrid",11),("Athletic Bilbao",8),
    ("Valencia",6),("Real Sociedad",2),("Deportivo La Coruña",1),("Sevilla",1),("Real Betis",1)],
  "ita": [("Juventus",36),("Inter Milan",21),("Milan",19),("Genoa",9),("Torino",7),("Bologna",7),
    ("Pro Vercelli",7),("Napoli",4),("Roma",3),("Lazio",2),("Fiorentina",2),("Casale",1),
    ("Novese",1),("Cagliari",1),("Hellas Verona",1),("Sampdoria",1)],
  "ger": [("Bayern Munich",35),("1. FC Nürnberg",9),("Borussia Dortmund",8),("Schalke 04",7),
    ("Hamburger SV",6),("VfB Stuttgart",5),("Borussia Mönchengladbach",5),("Werder Bremen",4),
    ("1. FC Kaiserslautern",4),("1. FC Köln",3),("Lokomotive Leipzig",3),("Greuther Fürth",3),
    ("Hertha BSC",2),("Viktoria Berlin",2),("Dresdner SC",2),("Hannover 96",2),("Bayer Leverkusen",1),
    ("Karlsruher FV",1),("Holstein Kiel",1),("1860 Munich",1),("Fortuna Düsseldorf",1),
    ("Eintracht Frankfurt",1),("VfL Wolfsburg",1),("Freiburger FC",1),("VfR Mannheim",1),
    ("Rot-Weiss Essen",1),("Eintracht Braunschweig",1)],
  "fra": [("Paris Saint-Germain",14),("Marseille",10),("Saint-Étienne",10),("Monaco",8),("Nantes",8),
    ("Lyon",7),("Bordeaux",6),("Lille",6),("Reims",6),("Standard Athletic Club",5),("RC Roubaix",5),
    ("Nice",4),("Stade Helvétique",3),("Le Havre",3),("RC Paris",2),("Sochaux",2),("Sète",2),
    ("Lens",1),("Strasbourg",1),("Auxerre",1),("Montpellier",1)],
}
out['palmares']=PALMARES

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
try:
    import urllib.request as _ur
    _req=_ur.Request("https://api.sleeper.app/v1/players/nfl",headers={"User-Agent":"Mozilla/5.0 (La Pizarra)"})
    with _ur.urlopen(_req,timeout=60) as _r: _spl=json.loads(_r.read().decode("utf-8"))
    _n=0
    for _sid,_p in _spl.items():
        if _p.get("position") not in ("QB","RB","WR","TE","K"): continue
        _prev=out['sleeper'].get(_sid)
        _g=(_prev[3] if _prev and _prev[3] else (_p.get("gsis_id") or "").strip())
        out['sleeper'][_sid]=[_p.get("full_name") or f"{_p.get('first_name','')} {_p.get('last_name','')}".strip(),_p.get("position"),_p.get("team") or "",_g]
        _n+=1
    print(f"Sleeper: {_n} jugadores en el mapa")
except Exception as _ex:
    print("Sleeper: no se pudo descargar la lista de jugadores:",_ex)
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

# ---------- NFL: calendario completo, detalle de partidos y power ranking ----------
def _i(v):
    return None if v is None or pd.isna(v) else int(v)
out['nflteams']={a:dict(n=teams.loc[a].team_nick,name=teams.loc[a].team_name,c=teams.loc[a].team_color,logo=teams.loc[a].team_logo_espn) for a in teams.index}
sched=[]
for r in full.sort_values(['week','gameday','gametime']).itertuples():
    tbd=not isinstance(r.gametime,str) or not r.gametime
    try:
        ko=datetime.strptime(f"{r.gameday} {r.gametime if not tbd else '12:00'}","%Y-%m-%d %H:%M").replace(tzinfo=ET).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%MZ")
    except Exception:
        ko=None
    sid=r.stadium_id if isinstance(r.stadium_id,str) and r.stadium_id else BYNAME.get(r.stadium)
    roof=r.roof if isinstance(r.roof,str) else None
    if sid in OPEN_AIR: roof="outdoors"
    ll=COORD.get(sid)
    sched.append(dict(id=r.game_id,w=int(r.week),ko=ko,tbd=tbd,a=r.away_team,h=r.home_team,st=r.stadium,roof=roof,
        lat=ll[0] if ll else None,lon=ll[1] if ll else None,aml=rnd(r.away_moneyline,0),hml=rnd(r.home_moneyline,0),
        sp=rnd(r.spread_line,1),tot=rnd(r.total_line,1),as_=_i(r.away_score),hs=_i(r.home_score)))
out['sched']=sched

box={}
done_ids=set(full[full.home_score.notna()].game_id)
pg=pbp[pbp.game_id.isin(done_ids)]
def nm2(x): return x if isinstance(x,str) else "?"
for gid,g in pg.groupby('game_id'):
    home,away=g.home_team.iloc[0],g.away_team.iloc[0]
    # marcador por cuarto
    q={away:[],home:[]}; pa=ph=0
    for qt in sorted(g.qtr.dropna().unique()):
        gg=g[g.qtr==qt]; ea=int(gg.total_away_score.max()); eh=int(gg.total_home_score.max())
        q[away].append(ea-pa); q[home].append(eh-ph); pa,ph=ea,eh
    # jugadas de anotación
    sc=[]
    for r in g[g.sp==1].itertuples():
        score=f"{int(r.total_away_score)}-{int(r.total_home_score)}"
        if (r.extra_point_attempt==1 or r.two_point_attempt==1):
            if sc: sc[-1]['s']=score
            continue
        if r.touchdown==1:
            tm=r.td_team if isinstance(r.td_team,str) else r.posteam
            if r.pass_touchdown==1: txt=f"TD: pase de {nm2(r.passer_player_name)} a {nm2(r.receiver_player_name)}, {int(r.yards_gained or 0)} yds"
            elif r.rush_touchdown==1: txt=f"TD: carrera de {nm2(r.rusher_player_name)}, {int(r.yards_gained or 0)} yds"
            else: txt=f"TD de {nm2(r.td_player_name)} (regreso)"
        elif r.field_goal_result=="made":
            tm=r.posteam; txt=f"Gol de campo de {nm2(r.kicker_player_name)}, {int(r.kick_distance or 0)} yds"
        elif r.safety==1:
            tm=r.defteam; txt="Safety"
        else:
            continue
        sc.append(dict(q=int(r.qtr),t=r.time,tm=tm,x=txt,s=score))
    # estadísticas de equipo
    pr=g[g.play_type.isin(['pass','run'])]
    ts={}
    for tm in (away,home):
        o=pr[pr.posteam==tm]; allp=g[g.posteam==tm]
        ts[tm]=dict(plays=len(o),yds=int(o.yards_gained.sum()),py=int(o[o.pass_attempt==1].yards_gained.sum()),ry=int(o[o.rush_attempt==1].yards_gained.sum()),
            epa=rnd(o.epa.mean(),2),fd=int(allp.first_down.fillna(0).sum()),
            d3=f"{int(allp.third_down_converted.fillna(0).sum())}/{int(allp.third_down_converted.fillna(0).sum()+allp.third_down_failed.fillna(0).sum())}",
            d4=f"{int(allp.fourth_down_converted.fillna(0).sum())}/{int(allp.fourth_down_converted.fillna(0).sum()+allp.fourth_down_failed.fillna(0).sum())}",
            to=int(allp.interception.fillna(0).sum()+allp.fumble_lost.fillna(0).sum()),sk=int(allp.sack.fillna(0).sum()),
            pen=f"{int(((g.penalty==1)&(g.penalty_team==tm)).sum())}-{int(g[(g.penalty==1)&(g.penalty_team==tm)].penalty_yards.fillna(0).sum())}")
    # jugadores
    wk=int(g.week.iloc[0]); pl={}
    for tm in (away,home):
        rows=ps[(ps.week==wk)&(ps.team==tm)]
        L=[]
        for r in rows.itertuples():
            d=dict(n=r.player_display_name,p=r.position)
            if (r.attempts or 0)>0: d['pa']=[int(r.completions),int(r.attempts),int(r.passing_yards or 0),int(r.passing_tds or 0),int(r.passing_interceptions or 0)]
            if (r.carries or 0)>0: d['ru']=[int(r.carries),int(r.rushing_yards or 0),int(r.rushing_tds or 0)]
            if (r.targets or 0)>0: d['re']=[int(r.receptions or 0),int(r.targets),int(r.receiving_yards or 0),int(r.receiving_tds or 0)]
            tk=(r.def_tackles_solo or 0)+(r.def_tackle_assists or 0)
            if tk>0 or (r.def_sacks or 0)>0 or (r.def_interceptions or 0)>0: d['df']=[int(tk),rnd(r.def_sacks,1) or 0,int(r.def_interceptions or 0)]
            f=r.fantasy_points_ppr
            if len(d)>2:
                if f is not None and not pd.isna(f) and ('pa' in d or 'ru' in d or 're' in d): d['ppr']=round(float(f),1)
                L.append(d)
        pl[tm]=L
    box[gid]=dict(q=q,sc=sc,ts=ts,pl=pl)
out['box']=box

# ----- Power ranking NFL -----
def team_metrics(pbp_,sch_,upto):
    p=pbp_[(pbp_.week<=upto)&pbp_.play_type.isin(['pass','run'])]
    off=p.groupby('posteam').epa.mean(); de=p.groupby('defteam').epa.mean()
    g=sch_[(sch_.week<=upto)&sch_.home_score.notna()]
    rows=[]
    for r in g.itertuples():
        rows.append((r.home_team,r.away_team,r.home_score,r.away_score,r.week)); rows.append((r.away_team,r.home_team,r.away_score,r.home_score,r.week))
    gm=pd.DataFrame(rows,columns=['tm','opp','pf','pa','wk'])
    pf=gm.groupby('tm').pf.mean(); pa=gm.groupby('tm').pa.mean()
    # forma: EPA neto en los últimos 3 partidos
    net_g=[]
    for (gid,tm),x in p.groupby(['game_id','posteam']): net_g.append((tm,x.week.iloc[0],x.epa.mean(),'o'))
    for (gid,tm),x in p.groupby(['game_id','defteam']): net_g.append((tm,x.week.iloc[0],-x.epa.mean(),'d'))
    ng=pd.DataFrame(net_g,columns=['tm','wk','v','k']).groupby(['tm','wk']).v.sum().reset_index()
    rec=ng.sort_values('wk').groupby('tm').tail(3).groupby('tm').v.mean()
    return dict(off=off,de=de,pf=pf,pa=pa,rec=rec,gm=gm)
def power_nfl(upto):
    cur=team_metrics(pbp_all,full,upto)
    wprev=max(0.0,0.7*(1-(upto-1)/5))
    prv=team_metrics(pbp_prev,sch_prev,99) if (wprev>0 and pbp_prev is not None) else None
    T=sorted(set(cur['gm'].tm))
    def bl(k,t):
        c=cur[k].get(t,np.nan)
        if prv is None: return c
        pv=prv[k].get(t,np.nan)
        if pd.isna(c): return pv
        if pd.isna(pv): return c
        return wprev*pv+(1-wprev)*c
    M=pd.DataFrame([dict(t=t,off=bl('off',t),de=bl('de',t),pf=bl('pf',t),pa=bl('pa',t),rec=bl('rec',t)) for t in T]).set_index('t')
    net=M.off-M.de
    sos=cur['gm'].groupby('tm').opp.apply(lambda o: np.nanmean([net.get(x,np.nan) for x in o]))
    M['sos']=sos
    z=lambda s:(s-s.mean())/(s.std(ddof=0) or 1)
    M['score']=0.225*z(M.off)+0.225*z(-M.de)+0.20*z(M.sos)+0.15*z(M.rec)+0.10*z(M.pf)+0.10*z(-M.pa)
    M=M.sort_values('score',ascending=False)
    M['rank']=range(1,len(M)+1)
    return M,wprev
pbp_all=pbp
try:
    pbp_prev=nfl.load_pbp(S-1).to_pandas(); pbp_prev=pbp_prev[pbp_prev.season_type=="REG"]
    sch_prev=nfl.load_schedules(S-1).to_pandas(); sch_prev=sch_prev[sch_prev.game_type=="REG"]
except Exception as ex:
    print("Power ranking: sin temporada pasada:",ex); pbp_prev=None; sch_prev=None
M,wprev=power_nfl(wk)
prevM=power_nfl(wk-1)[0] if wk>1 else None
aqui=os.path.dirname(os.path.abspath(__file__))
try: RJ=json.load(open(os.path.join(aqui,'ranking.json'),encoding='utf-8'))
except Exception: RJ={}
out['ranking_mx']=RJ.get('ligamx',{})
out['mx_jfix']=RJ.get('jornadas_mx',[])  # correcciones manuales de jornada para partidos aplazados que se confunden con la Liguilla

order=list(M.index)
for a in RJ.get('nfl',{}).get('ajustes',[]):
    t=a.get('equipo'); mv=int(a.get('mover',0) or 0)
    if t in order and mv:
        i=order.index(t); order.pop(i); order.insert(max(0,min(len(order),i-mv)),t)
com={a.get('equipo'):a.get('comentario','') for a in RJ.get('nfl',{}).get('ajustes',[])}
recs=rec_t.set_index('tm')
smin,smax=M.score.min(),M.score.max()
out['pr_nfl']=[dict(r=i+1,t=t,prev=int(prevM.loc[t,'rank']) if prevM is not None and t in prevM.index else None,
    sc=round(float((M.loc[t,'score']-smin)/((smax-smin) or 1)*100),1),w=int(recs.loc[t,'w']) if t in recs.index else 0,l=int(recs.loc[t,'l']) if t in recs.index else 0,
    off=rnd(M.loc[t,'off'],3),de=rnd(M.loc[t,'de'],3),pf=rnd(M.loc[t,'pf'],1),pa=rnd(M.loc[t,'pa'],1),sos=rnd(M.loc[t,'sos'],3),rec=rnd(M.loc[t,'rec'],3),c=com.get(t,'')) for i,t in enumerate(order)]
out['pr_wprev']=round(wprev*100)
print(f"Power ranking NFL: semana {wk}, peso temporada pasada {round(wprev*100)}%")

# ---------- Liga MX: estadísticas de jugadores partido por partido (ESPN) ----------
import urllib.request
from datetime import date, timedelta
def espn(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36","Accept":"application/json,text/plain,*/*","Accept-Language":"es-MX,es;q=0.9,en;q=0.8","Referer":"https://www.espn.com/","Origin":"https://www.espn.com"})
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))
def mx_player_stats():
    base="https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1"
    hoy=date.today().isoformat()
    base_sb=espn(f"{base}/scoreboard")
    lg=(base_sb.get("leagues") or [{}])[0]
    out['mx_logos']=[{"href":l.get("href"),"rel":l.get("rel",[])} for l in lg.get("logos",[])]
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
# ---------- Postemporada NFL, si la temporada terminara hoy ----------
# Sigue el orden oficial de desempate de la NFL (nfl.com/standings/tie-breaking-procedures):
# cabeza a cabeza → récord de división (empates de división) o de conferencia (comodines) → rivales en
# común (mín. 4 partidos) → récord de conferencia (empates de división) → fuerza de victoria → fuerza de
# calendario → diferencia de puntos. Se omiten, por ser extremadamente raro que se necesiten y requerir
# datos que no se calculan aquí, los últimos pasos oficiales: clasificación combinada de puntos anotados
# y recibidos, diferencia de touchdowns y volado. En un empate a 3+ equipos, la regla oficial reevalúa
# desde el paso 1 en cuanto quedan solo 2 con la misma marca; aquí se hace lo mismo.
def nfl_seeds():
    conf=teams['team_conf'].to_dict(); div=teams['team_division'].to_dict()
    g2=gm.copy(); g2['t_conf']=g2.tm.map(conf); g2['t_div']=g2.tm.map(div)
    g2['o_conf']=g2.opp.map(conf); g2['o_div']=g2.opp.map(div)
    PCT=rec_t.set_index('tm').pct.to_dict()
    def pct_of(rows):
        n=len(rows)
        return None if n==0 else (rows.w.sum()+0.5*rows.tie.sum())/n
    def h2h(a,b):
        rows=g2[(g2.tm==a)&(g2.opp==b)]
        return pct_of(rows)
    def div_pct(t): return pct_of(g2[(g2.tm==t)&(g2.t_div==g2.o_div)])
    def conf_pct(t): return pct_of(g2[(g2.tm==t)&(g2.t_conf==g2.o_conf)])
    def common_pct(t,opps):
        rows=g2[(g2.tm==t)&(g2.opp.isin(opps))]
        return pct_of(rows) if len(rows)>=4 else None
    def sov(t):
        rows=g2[(g2.tm==t)&(g2.w==1)]
        return np.mean([PCT.get(o,0) for o in rows.opp]) if len(rows) else None
    def sos(t):
        rows=g2[g2.tm==t]
        return np.mean([PCT.get(o,0) for o in rows.opp]) if len(rows) else None
    def diff(t):
        r=rec_t.set_index('tm').loc[t]; return r.pf-r.pa
    def h2h_group(group):
        # Solo cuenta si TODOS los equipos del grupo se han enfrentado entre sí (barrida/round-robin).
        need=[(a,b) for i,a in enumerate(group) for b in group[i+1:]]
        if any(g2[(g2.tm==a)&(g2.opp==b)].empty for a,b in need): return {t:None for t in group}
        return {t:pct_of(g2[(g2.tm==t)&(g2.opp.isin([x for x in group if x!=t]))]) for t in group}
    def common_group(group):
        opp_sets=[set(g2[g2.tm==t].opp) for t in group]
        common=set.intersection(*opp_sets) if opp_sets else set()
        return {t:common_pct(t,common) for t in group}
    def resolve(group,division_tie):
        # Ordena TODO el grupo empatado, no solo escoge un ganador: en cada paso separa al subgrupo que
        # va mejor (y lo sigue afinando entre sí desde el paso 1, como marca la regla oficial), ordena por
        # su cuenta al resto, y los concatena. Si el empate sigue hasta el final, deja el orden en que venía
        # (equivalente al volado oficial, el único paso que no se reproduce aquí).
        if len(group)<=1: return list(group)
        steps=[('h2h',h2h_group)]
        if division_tie: steps.append(('div',lambda grp:{t:div_pct(t) for t in grp}))
        steps.append(('common',common_group))
        steps.append(('conf',lambda grp:{t:conf_pct(t) for t in grp}))
        steps+= [('sov',lambda grp:{t:sov(t) for t in grp}),('sos',lambda grp:{t:sos(t) for t in grp}),('diff',lambda grp:{t:diff(t) for t in grp})]
        for name,fn in steps:
            vals=fn(group)
            if any(v is None for v in vals.values()): continue
            mx=max(vals.values()); top=[t for t in group if abs(vals[t]-mx)<1e-9]
            if 0<len(top)<len(group):
                rest=[t for t in group if t not in top]
                return resolve(top,division_tie)+resolve(rest,division_tie)
        return group
    def order(group,division_tie):
        buckets={}
        for t in group: buckets.setdefault(round(PCT[t],9),[]).append(t)
        out=[]
        for p in sorted(buckets,reverse=True):
            grp=buckets[p]
            out+= grp if len(grp)==1 else resolve(grp,division_tie)
        return out
    res={}
    for c in ['AFC','NFC']:
        cteams=[t for t,cc in conf.items() if cc==c and t in PCT]
        by_div={}
        for t in cteams: by_div.setdefault(div[t],[]).append(t)
        leaders=[order(ts,True)[0] for ts in by_div.values()]
        leaders=order(leaders,False)
        rest=order([t for t in cteams if t not in leaders],False)[:3]
        seeds=leaders+rest
        rt=rec_t.set_index('tm')
        res[c]=[dict(seed=i+1,t=t,div=div[t].replace(c+' ',''),w=int(rt.loc[t].w),l=int(rt.loc[t].l),tie=int(rt.loc[t].tie),div_leader=bool(i<4)) for i,t in enumerate(seeds)]
    return res
try:
    out['nfl_seeds']=nfl_seeds()
except Exception as ex:
    print("Postemporada NFL: no se pudo calcular:",ex); out['nfl_seeds']={}
out['week']=wk; out['winners']=sorted(winners)
data=json.dumps(out,ensure_ascii=False,allow_nan=False)
aqui=os.path.dirname(os.path.abspath(__file__))
notas=json.load(open(os.path.join(aqui,'notas.json'),encoding='utf-8'))
notas_js=json.dumps([[n['jugador'],n['posicion'],n['equipo'],n['texto']] for n in notas['notas']],ensure_ascii=False)
html=open(os.path.join(aqui,'template.html'),encoding='utf-8').read().replace('__DATA__',data).replace('__NOTES__',notas_js)
os.makedirs(os.path.join(aqui,'docs'),exist_ok=True)
open(os.path.join(aqui,'docs','index.html'),'w',encoding='utf-8').write(html)
print(f'Listo: docs/index.html (temporada {S}, semana {wk})')
