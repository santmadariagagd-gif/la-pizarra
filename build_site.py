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
out['qb']=[dict(n=r.n,t=r.tm,plays=int(r.plays),epa=round(r.epa,3),cpoe=round(r.cpoe,1) if pd.notna(r.cpoe) else None,yds=int(r.yds),td=int(r.td),int=int(r.int_),ypa=round(r.ypa,1)) for r in qb.itertuples()]
# receivers
rec=ps[ps.position.isin(['WR','TE','RB'])].groupby('player_id').agg(rec=('receptions','sum'),tgt=('targets','sum'),yds=('receiving_yards','sum'),td=('receiving_tds','sum'),yac=('receiving_yards_after_catch','sum'),ts=('target_share','mean')).reset_index()
rec=rec.merge(names,on='player_id'); rec=rec[rec.tgt>=5]
rec['ypr']=rec.yds/rec.rec.replace(0,np.nan)
out['rec']=[dict(n=r.n,p=r.pos,t=r.tm,rec=int(r.rec),tgt=int(r.tgt),yds=int(r.yds),td=int(r.td),ypr=round(r.ypr,1) if pd.notna(r.ypr) else 0,ts=round(float(r.ts or 0),3)) for r in rec.itertuples()]
# rushers
ru=pbp[(pbp.rush_attempt==1)&pbp.rusher_player_id.notna()].groupby('rusher_player_id').agg(car=('epa','size'),epa=('epa','mean'),yds=('rushing_yards','sum'),td=('rush_touchdown','sum')).reset_index()
ru=nm(ru,'rusher_player_id'); ru=ru[(ru.car>=10)&(ru.pos.isin(['RB','QB','WR']))]
ru['ypc']=ru.yds/ru.car
out['rush']=[dict(n=r.n,p=r.pos,t=r.tm,car=int(r.car),yds=int(r.yds),td=int(r.td),ypc=round(r.ypc,1),epa=round(r.epa,3)) for r in ru.itertuples()]
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
    fan.append(dict(n=r.player,p=r.pos,t=r.team,own=round(float(r.player_owned_avg),1) if pd.notna(r.player_owned_avg) else None,
        ecr=round(float(r.ecr_ov),1) if pd.notna(r.ecr_ov) else None, pr=round(float(r.ecr),1),
        ppg=round(float(tot.loc[pid].ppr/tot.loc[pid].g),1) if isinstance(pid,str) and pid in tot.index else None,
        opp=opp(L), opp0=opp(P),
        snap=round(float(snl.get(pid,np.nan)),2) if isinstance(pid,str) and pd.notna(snl.get(pid,np.nan)) else None,
        snap0=round(float(snp.get(pid,np.nan)),2) if isinstance(pid,str) and pd.notna(snp.get(pid,np.nan)) else None))
out['fantasy']=fan
out['week']=wk; out['winners']=sorted(winners)
data=json.dumps(out,ensure_ascii=False,allow_nan=False)
aqui=os.path.dirname(os.path.abspath(__file__))
notas=json.load(open(os.path.join(aqui,'notas.json'),encoding='utf-8'))
notas_js=json.dumps([[n['jugador'],n['posicion'],n['equipo'],n['texto']] for n in notas['notas']],ensure_ascii=False)
html=open(os.path.join(aqui,'template.html'),encoding='utf-8').read().replace('__DATA__',data).replace('__NOTES__',notas_js)
os.makedirs(os.path.join(aqui,'docs'),exist_ok=True)
open(os.path.join(aqui,'docs','index.html'),'w',encoding='utf-8').write(html)
print(f'Listo: docs/index.html (temporada {S}, semana {wk})')
