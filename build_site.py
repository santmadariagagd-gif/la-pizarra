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
# ---------- Fotos de jugadores de las 5 ligas europeas: Wikimedia Commons (vía Wikidata) ----------
# Igual que se probó para Liga MX: una consulta SPARQL por liga y por actualización, futbolistas de
# clubes de ese país con foto libre en Commons. Liga MX se queda con escudos (así lo prefirió Santiago).
# El emparejamiento (nombre EXACTO + club) se hace en el navegador, igual que antes.
import urllib.request, urllib.parse
def wd_query_text(country_qid):
    return f"""SELECT ?j ?nombre ?clubLabel ?foto WHERE {{
  ?club wdt:P17 wd:{country_qid} ; wdt:P31 wd:Q476028 .
  ?j p:P54 ?st . ?st ps:P54 ?club .
  FILTER NOT EXISTS {{ ?st pq:P582 ?fin }}
  ?j wdt:P106 wd:Q937857 ; wdt:P18 ?foto ; wdt:P569 ?nac .
  FILTER(YEAR(?nac) >= 1983)
  ?j rdfs:label ?nombre . FILTER(LANG(?nombre) IN ("es","en","mul"))
  OPTIONAL {{ ?club rdfs:label ?clubLabel . FILTER(LANG(?clubLabel) = "en") }}
}}"""
def wd_photos(q):
    url="https://query.wikidata.org/sparql?format=json&query="+urllib.parse.quote(q)
    req=urllib.request.Request(url,headers={"User-Agent":"LaPizarra/1.0 (https://lapizarra.mx)","Accept":"application/sparql-results+json"})
    with urllib.request.urlopen(req,timeout=90) as r: j=json.loads(r.read().decode("utf-8"))
    P={}
    for b in j["results"]["bindings"]:
        qid=b["j"]["value"].rsplit("/",1)[-1]
        e=P.setdefault(qid,[set(),set(),None])
        e[0].add(b["nombre"]["value"])
        if "clubLabel" in b: e[1].add(b["clubLabel"]["value"])
        if not e[2]: e[2]=urllib.parse.unquote(b["foto"]["value"].rsplit("/",1)[-1])
    return [[sorted(n),sorted(c),f] for n,c,f in P.values() if f]
WD_COUNTRIES={"eng":"Q21","esp":"Q29","ita":"Q38","ger":"Q183","fra":"Q142"}
out['wd_photos']={}; out['wd_photos_q']={}
for code,qid in WD_COUNTRIES.items():
    q=wd_query_text(qid); out['wd_photos_q'][code]=q  # se manda siempre, para que el navegador la use si esto falla
    try:
        rows=wd_photos(q)
        out['wd_photos'][code]=rows
        print(f"Fotos {code}: {len(rows)} futbolistas con foto libre")
    except Exception as ex:
        print(f"Fotos {code}: no se pudo consultar Wikidata desde GitHub (la página lo intentará desde el navegador):",ex)
        out['wd_photos'][code]=[]

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
# Champions League (Copa de Europa + Champions): títulos por club. Fuente: Wikipedia "List of European Cup
# and UEFA Champions League finals" (actualizada con la final de 2026), cruzada con UEFA.com.
PALMARES['ucl']=[("Real Madrid",15),("Milan",7),("Bayern Munich",6),("Liverpool",6),("Barcelona",5),("Ajax",4),
    ("Inter",3),("Manchester United",3),("Juventus",2),("Benfica",2),("Chelsea",2),("Paris Saint-Germain",2),
    ("Nottingham Forest",2),("Porto",2),("Borussia Dortmund",1),("Celtic",1),("Hamburgo",1),("Steaua București",1),
    ("Olympique de Marsella",1),("Manchester City",1),("Feyenoord",1),("Aston Villa",1),("PSV Eindhoven",1),("Estrella Roja",1)]
out['palmares']=PALMARES

# Historia de la Liga MX (era profesional, desde 1943-44). Una fila por temporada o torneo:
# (temporada, campeón, subcampeón, final, [(goleador, club), ...], goles)
# final = "" cuando se decidió por puntos. goles = None cuando las fuentes no coinciden en la cifra.
# Fuentes: RSSSF "Mexico - List of Champions" y "List of Topscorers", cruzadas con Wikipedia
# ("List of Mexican football champions", "List of Mexican league top scorers"); Apertura 2025 y
# Clausura 2026 confirmados en prensa (Excélsior, Mediotiempo, TUDN). Actualizar a mano cada torneo.
HIST_MX = [
  ("1943-44","Asturias","Real España","4-1 en partido de desempate",[("Isidro Lángara","Real España")],27),
  ("1944-45","Real España","Puebla","",[("Roberto Aballay","Asturias")],40),
  ("1945-46","Veracruz","Atlante","",[("Isidro Lángara","Real España")],40),
  ("1946-47","Atlante","León","",[("Adalberto López","León")],None),
  ("1947-48","León","Oro","2-0 en partido de desempate",[("Adalberto López","León")],None),
  ("1948-49","León","Atlas","",[("Adalberto López","León")],None),
  ("1949-50","Veracruz","Atlante","",[("Julio Ayllón","Veracruz")],30),
  ("1950-51","Atlas","Atlante","",[("Horacio Casarín","Necaxa")],17),
  ("1951-52","León","Guadalajara","",[("Adalberto López","Oro")],None),
  ("1952-53","Tampico","Zacatepec","",[("Julio Quiñones","Necaxa")],14),
  ("1953-54","Marte","Oro","",[("Juan Carlos Carrera","Oro"),("Julio María Palleiro","Necaxa")],21),
  ("1954-55","Zacatepec","Guadalajara","",[("Julio María Palleiro","Necaxa")],19),
  ("1955-56","León","Oro","4-2 en partido de desempate",[("Héctor Hernández","Oro")],25),
  ("1956-57","Guadalajara","Toluca","",[("Crescencio Gutiérrez","Guadalajara")],19),
  ("1957-58","Zacatepec","Toluca","",[("Carlos Lara","Zacatepec")],19),
  ("1958-59","Guadalajara","León","",[("Eduardo González Palmer","América")],None),
  ("1959-60","Guadalajara","América","",[("Roberto Rolando","Tampico")],22),
  ("1960-61","Guadalajara","Oro","",[("Carlos Lara","Zacatepec")],22),
  ("1961-62","Guadalajara","América","",[("Salvador Reyes","Guadalajara"),("Carlos Lara","Zacatepec")],21),
  ("1962-63","Oro","Guadalajara","",[("Amaury Epaminondas","Oro")],19),
  ("1963-64","Guadalajara","América","",[("Alberto Etcheverry","Pumas UNAM")],20),
  ("1964-65","Guadalajara","Oro","",[("Amaury Epaminondas","Oro")],21),
  ("1965-66","América","Atlas","",[("José Alves «Zague»","América")],20),
  ("1966-67","Toluca","América","",[("Amaury Epaminondas","Toluca")],21),
  ("1967-68","Toluca","Pumas UNAM","",[("Bernardo Hernández","Atlante")],19),
  ("1968-69","Cruz Azul","Guadalajara","",[("Luis Estrada","León")],24),
  ("1969-70","Guadalajara","Cruz Azul","",[("Vicente Pereda","Toluca")],20),
  ("México 70","Cruz Azul","Guadalajara","",[("Sergio Anaya","León")],None),
  ("1970-71","América","Toluca","2-0 global",[("Enrique Borja","América")],20),
  ("1971-72","Cruz Azul","América","4-1",[("Enrique Borja","América")],26),
  ("1972-73","Cruz Azul","León","1-1 global; 2-1 en desempate",[("Enrique Borja","América")],24),
  ("1973-74","Cruz Azul","Atlético Español","4-2 global",[("Osvaldo Castro","América")],26),
  ("1974-75","Toluca","León","Grupo final",[("Horacio López Salgado","Cruz Azul")],25),
  ("1975-76","América","Leones Negros UdeG","4-0 global",[("Cabinho","Pumas UNAM")],29),
  ("1976-77","Pumas UNAM","Leones Negros UdeG","1-0 global",[("Cabinho","Pumas UNAM")],34),
  ("1977-78","Tigres UANL","Pumas UNAM","3-1 global",[("Cabinho","Pumas UNAM")],33),
  ("1978-79","Cruz Azul","Pumas UNAM","2-0 global",[("Cabinho","Pumas UNAM"),("Hugo Sánchez","Pumas UNAM")],26),
  ("1979-80","Cruz Azul","Tigres UANL","4-3 global",[("Cabinho","Atlante")],30),
  ("1980-81","Pumas UNAM","Cruz Azul","4-2 global",[("Cabinho","Atlante")],29),
  ("1981-82","Tigres UANL","Atlante","2-2 global (3-1 en penales)",[("Cabinho","Atlante")],32),
  ("1982-83","Puebla","Guadalajara","2-2 global (7-6 en penales)",[("Norberto Outes","América")],22),
  ("1983-84","América","Guadalajara","5-3 global",[("Norberto Outes","Necaxa")],28),
  ("1984-85","América","Pumas UNAM","1-1 global; 3-1 en desempate",[("Cabinho","León")],23),
  ("Prode 85","América","Tampico Madero","5-4 global (tiempo extra)",[("Sergio Lira","Tampico Madero")],10),
  ("México 86","Monterrey","Tampico Madero","3-2 global (tiempo extra)",[("Sergio Lira","Tampico Madero"),("Francisco Javier Cruz","Monterrey")],14),
  ("1986-87","Guadalajara","Cruz Azul","4-2 global",[("José Luis Zalazar","Tecos")],23),
  ("1987-88","América","Pumas UNAM","4-2 global",[("Luis Flores","Pumas UNAM")],24),
  ("1988-89","América","Cruz Azul","5-4 global",[("Sergio Lira","Tampico Madero")],29),
  ("1989-90","Puebla","Leones Negros UdeG","6-4 global",[("Jorge Comas","Veracruz")],26),
  ("1990-91","Pumas UNAM","América","3-3 global (gol de visitante)",[("Luis García","Pumas UNAM")],None),
  ("1991-92","León","Puebla","2-0 global (tiempo extra)",[("Luis García","Pumas UNAM")],None),
  ("1992-93","Atlante","Monterrey","4-0 global",[("Ivo Basay","Necaxa")],27),
  ("1993-94","Tecos","Santos Laguna","2-1 global (tiempo extra)",[("Carlos Hermosillo","Cruz Azul")],27),
  ("1994-95","Necaxa","Cruz Azul","3-1 global",[("Carlos Hermosillo","Cruz Azul")],35),
  ("1995-96","Necaxa","Celaya","1-1 global (gol de visitante)",[("Carlos Hermosillo","Cruz Azul")],26),
  ("Invierno 1996","Santos Laguna","Necaxa","4-3 global",[("Carlos Muñoz","Puebla")],15),
  ("Verano 1997","Guadalajara","Toros Neza","7-2 global",[("Lorenzo Sáez","Pachuca"),("Gabriel Caballero","Santos Laguna")],12),
  ("Invierno 1997","Cruz Azul","León","2-1 global (gol de oro)",[("Luis García","Atlante")],12),
  ("Verano 1998","Toluca","Necaxa","6-4 global",[("José Cardozo","Toluca")],13),
  ("Invierno 1998","Necaxa","Guadalajara","2-0 global",[("Cuauhtémoc Blanco","América")],16),
  ("Verano 1999","Toluca","Atlas","5-5 global (5-4 en penales)",[("José Cardozo","Toluca")],15),
  ("Invierno 1999","Pachuca","Cruz Azul","3-2 global (gol de oro)",[("Jesús Olalde","Pumas UNAM")],15),
  ("Verano 2000","Toluca","Santos Laguna","7-1 global",[("Agustín Delgado","Necaxa"),("Sebastián Abreu","Tecos"),("Everaldo Begines","León")],14),
  ("Invierno 2000","Morelia","Toluca","3-3 global (5-4 en penales)",[("Jared Borgetti","Santos Laguna")],17),
  ("Verano 2001","Santos Laguna","Pachuca","4-3 global",[("Jared Borgetti","Santos Laguna")],13),
  ("Invierno 2001","Pachuca","Tigres UANL","3-1 global",[("Martín Rodríguez","Irapuato")],12),
  ("Verano 2002","América","Necaxa","3-2 global (gol de oro)",[("Sebastián Abreu","Cruz Azul")],19),
  ("Apertura 2002","Toluca","Morelia","4-2 global",[("José Cardozo","Toluca")],29),
  ("Clausura 2003","Monterrey","Morelia","3-1 global",[("José Cardozo","Toluca")],21),
  ("Apertura 2003","Pachuca","Tigres UANL","3-2 global",[("Luis Gabriel Rey","Atlante")],15),
  ("Clausura 2004","Pumas UNAM","Guadalajara","1-1 global (5-4 en penales)",[("Andrés Silvera","Tigres UANL"),("Bruno Marioni","Pumas UNAM")],16),
  ("Apertura 2004","Pumas UNAM","Monterrey","3-1 global",[("Guillermo Franco","Monterrey")],15),
  ("Clausura 2005","América","Tecos","7-4 global",[("Matías Vuoso","Santos Laguna")],15),
  ("Apertura 2005","Toluca","Monterrey","6-3 global",[("Matías Vuoso","Santos Laguna"),("Walter Gaitán","Tigres UANL"),("Kléber Pereira","América"),("Sebastián Abreu","Dorados")],11),
  ("Clausura 2006","Pachuca","San Luis","1-0 global",[("Sebastián Abreu","Dorados"),("Salvador Cabañas","Jaguares")],11),
  ("Apertura 2006","Guadalajara","Toluca","3-2 global",[("Bruno Marioni","Toluca")],11),
  ("Clausura 2007","Pachuca","América","3-2 global",[("Omar Bravo","Guadalajara")],11),
  ("Apertura 2007","Atlante","Pumas UNAM","2-1 global",[("Alfredo Moreno","San Luis")],18),
  ("Clausura 2008","Santos Laguna","Cruz Azul","3-2 global",[("Humberto Suazo","Monterrey")],13),
  ("Apertura 2008","Toluca","Cruz Azul","2-2 global (7-6 en penales)",[("Héctor Mancilla","Toluca")],11),
  ("Clausura 2009","Pumas UNAM","Pachuca","3-2 global (tiempo extra)",[("Héctor Mancilla","Toluca")],14),
  ("Apertura 2009","Monterrey","Cruz Azul","6-4 global",[("Emanuel Villa","Cruz Azul")],17),
  ("Bicentenario 2010","Toluca","Santos Laguna","2-2 global (4-3 en penales)",[("Javier Hernández","Guadalajara"),("Johan Fano","Atlante"),("Hérculez Gómez","Puebla")],10),
  ("Apertura 2010","Monterrey","Santos Laguna","5-3 global",[("Christian Benítez","Santos Laguna")],14),
  ("Clausura 2011","Pumas UNAM","Morelia","3-2 global",[("Ángel Reyna","América")],13),
  ("Apertura 2011","Tigres UANL","Santos Laguna","4-1 global",[("Iván Alonso","Toluca")],11),
  ("Clausura 2012","Santos Laguna","Monterrey","3-2 global",[("Iván Alonso","Toluca"),("Christian Benítez","América")],14),
  ("Apertura 2012","Tijuana","Toluca","4-1 global",[("Christian Benítez","América"),("Esteban Paredes","Atlante")],11),
  ("Clausura 2013","América","Cruz Azul","2-2 global (4-2 en penales)",[("Christian Benítez","América")],None),
  ("Apertura 2013","León","América","5-1 global",[("Pablo Velázquez","Toluca")],12),
  ("Clausura 2014","León","Pachuca","4-3 global (tiempo extra)",[("Enner Valencia","Pachuca")],12),
  ("Apertura 2014","América","Tigres UANL","3-1 global",[("Mauro Boselli","León"),("Camilo Sanvezzo","Querétaro")],12),
  ("Clausura 2015","Santos Laguna","Querétaro","5-3 global",[("Dorlan Pabón","Monterrey")],10),
  ("Apertura 2015","Tigres UANL","Pumas UNAM","4-4 global (4-2 en penales)",[("Mauro Boselli","León"),("Emanuel Villa","Querétaro")],13),
  ("Clausura 2016","Pachuca","Monterrey","2-1 global",[("André-Pierre Gignac","Tigres UANL")],13),
  ("Apertura 2016","Tigres UANL","América","2-2 global (3-0 en penales)",[("Dayro Moreno","Tijuana"),("Raúl Ruidíaz","Morelia")],11),
  ("Clausura 2017","Guadalajara","Tigres UANL","4-3 global",[("Raúl Ruidíaz","Morelia")],9),
  ("Apertura 2017","Tigres UANL","Monterrey","3-2 global",[("Mauro Boselli","León"),("Avilés Hurtado","Monterrey")],11),
  ("Clausura 2018","Santos Laguna","Toluca","3-2 global",[("Djaniny","Santos Laguna")],14),
  ("Apertura 2018","América","Cruz Azul","2-0 global",[("André-Pierre Gignac","Tigres UANL")],14),
  ("Clausura 2019","Tigres UANL","León","1-0 global",[("Ángel Mena","León")],14),
  ("Apertura 2019","Monterrey","América","3-3 global (4-2 en penales)",[("Mauro Quiroga","Necaxa"),("Alan Pulido","Guadalajara")],12),
  ("Clausura 2020",None,None,"Cancelado por la pandemia",[],None),
  ("Guardianes 2020","León","Pumas UNAM","3-1 global",[("Jonathan Rodríguez","Cruz Azul")],12),
  ("Guardianes 2021","Cruz Azul","Santos Laguna","2-1 global",[("Alexis Canelo","Toluca")],11),
  ("Apertura 2021","Atlas","León","3-3 global (4-3 en penales)",[("Nicolás López","Tigres UANL"),("Germán Berterame","San Luis")],9),
  ("Clausura 2022","Atlas","Pachuca","3-2 global",[("André-Pierre Gignac","Tigres UANL")],11),
  ("Apertura 2022","Pachuca","Toluca","8-2 global",[("Nicolás Ibáñez","Pachuca")],11),
  ("Clausura 2023","Tigres UANL","Guadalajara","3-2 global (tiempo extra)",[("Henry Martín","América")],14),
  ("Apertura 2023","América","Tigres UANL","4-1 global (tiempo extra)",[("Harold Preciado","Santos Laguna")],11),
  ("Clausura 2024","América","Cruz Azul","2-1 global",[("Uriel Antuna","Cruz Azul"),("Salomón Rondón","Pachuca"),("Diber Cambindo","Necaxa"),("Federico Viñas","León")],8),
  ("Apertura 2024","América","Monterrey","3-2 global",[("Paulinho","Toluca")],13),
  ("Clausura 2025","Toluca","América","2-0 global",[("Paulinho","Toluca"),("Uroš Đurđević","Atlas"),("Raúl Zúñiga","Tijuana")],12),
  ("Apertura 2025","Toluca","Tigres UANL","2-2 global (9-8 en penales)",[("Paulinho","Toluca"),("Armando González","Guadalajara"),("João Pedro","San Luis")],12),
  ("Clausura 2026","Cruz Azul","Pumas UNAM","2-1 global",[("João Pedro","San Luis")],14),
]

# Historia por temporada, una lista por competencia (misma clave que LEAGUES en la página).
# Para agregar otra liga: HISTORIA['eng']=HIST_ENG, etc.
# Historia de la NFL (1920 a hoy). (temporada, campeón, subcampeón, final, [(MVP, equipo), ...], None)
# 1920-1932: campeón por récord; 1933-1965: Juego de Campeonato de la NFL; 1966 en adelante: Super Bowl
# (la temporada es el año en que empieza; el Super Bowl se juega en febrero del año siguiente).
# MVP de AP desde 1957 (en 1960 AP no lo entregó; en 1997 y 2003 fue compartido).
# Fuentes: Wikipedia "List of NFL champions (1920–1969)", Topend Sports "Super Bowl Winners List",
# Bleacher Nation "NFL MVP Winners" (cruzado con los récords de MVP de Pro Football Reference).
_SB=["I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII","XIII","XIV","XV","XVI","XVII","XVIII","XIX","XX",
     "XXI","XXII","XXIII","XXIV","XXV","XXVI","XXVII","XXVIII","XXIX","XXX","XXXI","XXXII","XXXIII","XXXIV","XXXV",
     "XXXVI","XXXVII","XXXVIII","XXXIX","XL","XLI","XLII","XLIII","XLIV","XLV","XLVI","XLVII","XLVIII","XLIX","50",
     "LI","LII","LIII","LIV","LV","LVI","LVII","LVIII","LIX","LX"]
_PRE=[("1920","Akron Pros","Decatur Staleys",""),("1921","Chicago Staleys","Buffalo All-Americans",""),
  ("1922","Canton Bulldogs","Chicago Bears",""),("1923","Canton Bulldogs","Chicago Bears",""),
  ("1924","Cleveland Bulldogs","Chicago Bears",""),("1925","Chicago Cardinals","Pottsville Maroons",""),
  ("1926","Frankford Yellow Jackets","Chicago Bears",""),("1927","New York Giants","Green Bay Packers",""),
  ("1928","Providence Steam Roller","Frankford Yellow Jackets",""),("1929","Green Bay Packers","New York Giants",""),
  ("1930","Green Bay Packers","New York Giants",""),("1931","Green Bay Packers","Portsmouth Spartans",""),
  ("1932","Chicago Bears","Green Bay Packers",""),
  ("1933","Chicago Bears","New York Giants","23-21"),("1934","New York Giants","Chicago Bears","30-13"),
  ("1935","Detroit Lions","New York Giants","26-7"),("1936","Green Bay Packers","Boston Redskins","21-6"),
  ("1937","Washington","Chicago Bears","28-21"),("1938","New York Giants","Green Bay Packers","23-17"),
  ("1939","Green Bay Packers","New York Giants","27-0"),("1940","Chicago Bears","Washington","73-0"),
  ("1941","Chicago Bears","New York Giants","37-9"),("1942","Washington","Chicago Bears","14-6"),
  ("1943","Chicago Bears","Washington","41-21"),("1944","Green Bay Packers","New York Giants","14-7"),
  ("1945","Cleveland Rams","Washington","15-14"),("1946","Chicago Bears","New York Giants","24-14"),
  ("1947","Chicago Cardinals","Philadelphia Eagles","28-21"),("1948","Philadelphia Eagles","Chicago Cardinals","7-0"),
  ("1949","Philadelphia Eagles","Los Angeles Rams","14-0"),("1950","Cleveland Browns","Los Angeles Rams","30-28"),
  ("1951","Los Angeles Rams","Cleveland Browns","24-17"),("1952","Detroit Lions","Cleveland Browns","17-7"),
  ("1953","Detroit Lions","Cleveland Browns","17-16"),("1954","Cleveland Browns","Detroit Lions","56-10"),
  ("1955","Cleveland Browns","Los Angeles Rams","38-14"),("1956","New York Giants","Chicago Bears","47-7"),
  ("1957","Detroit Lions","Cleveland Browns","59-14"),("1958","Baltimore Colts","New York Giants","23-17"),
  ("1959","Baltimore Colts","New York Giants","31-16"),("1960","Philadelphia Eagles","Green Bay Packers","17-13"),
  ("1961","Green Bay Packers","New York Giants","37-0"),("1962","Green Bay Packers","New York Giants","16-7"),
  ("1963","Chicago Bears","New York Giants","14-10"),("1964","Cleveland Browns","Baltimore Colts","27-0"),
  ("1965","Green Bay Packers","Cleveland Browns","23-12")]
_SBR=[("Green Bay Packers","Kansas City Chiefs","35-10"),("Green Bay Packers","Oakland Raiders","33-14"),
  ("New York Jets","Baltimore Colts","16-7"),("Kansas City Chiefs","Minnesota Vikings","23-7"),
  ("Baltimore Colts","Dallas Cowboys","16-13"),("Dallas Cowboys","Miami Dolphins","24-3"),
  ("Miami Dolphins","Washington","14-7"),("Miami Dolphins","Minnesota Vikings","24-7"),
  ("Pittsburgh Steelers","Minnesota Vikings","16-6"),("Pittsburgh Steelers","Dallas Cowboys","21-17"),
  ("Oakland Raiders","Minnesota Vikings","32-14"),("Dallas Cowboys","Denver Broncos","27-10"),
  ("Pittsburgh Steelers","Dallas Cowboys","35-31"),("Pittsburgh Steelers","Los Angeles Rams","31-19"),
  ("Oakland Raiders","Philadelphia Eagles","27-10"),("San Francisco 49ers","Cincinnati Bengals","26-21"),
  ("Washington","Miami Dolphins","27-17"),("Los Angeles Raiders","Washington","38-9"),
  ("San Francisco 49ers","Miami Dolphins","38-16"),("Chicago Bears","New England Patriots","46-10"),
  ("New York Giants","Denver Broncos","39-20"),("Washington","Denver Broncos","42-10"),
  ("San Francisco 49ers","Cincinnati Bengals","20-16"),("San Francisco 49ers","Denver Broncos","55-10"),
  ("New York Giants","Buffalo Bills","20-19"),("Washington","Buffalo Bills","37-24"),
  ("Dallas Cowboys","Buffalo Bills","52-17"),("Dallas Cowboys","Buffalo Bills","30-13"),
  ("San Francisco 49ers","San Diego Chargers","49-26"),("Dallas Cowboys","Pittsburgh Steelers","27-17"),
  ("Green Bay Packers","New England Patriots","35-21"),("Denver Broncos","Green Bay Packers","31-24"),
  ("Denver Broncos","Atlanta Falcons","34-19"),("St. Louis Rams","Tennessee Titans","23-16"),
  ("Baltimore Ravens","New York Giants","34-7"),("New England Patriots","St. Louis Rams","20-17"),
  ("Tampa Bay Buccaneers","Oakland Raiders","48-21"),("New England Patriots","Carolina Panthers","32-29"),
  ("New England Patriots","Philadelphia Eagles","24-21"),("Pittsburgh Steelers","Seattle Seahawks","21-10"),
  ("Indianapolis Colts","Chicago Bears","29-17"),("New York Giants","New England Patriots","17-14"),
  ("Pittsburgh Steelers","Arizona Cardinals","27-23"),("New Orleans Saints","Indianapolis Colts","31-17"),
  ("Green Bay Packers","Pittsburgh Steelers","31-25"),("New York Giants","New England Patriots","21-17"),
  ("Baltimore Ravens","San Francisco 49ers","34-31"),("Seattle Seahawks","Denver Broncos","43-8"),
  ("New England Patriots","Seattle Seahawks","28-24"),("Denver Broncos","Carolina Panthers","24-10"),
  ("New England Patriots","Atlanta Falcons","34-28"),("Philadelphia Eagles","New England Patriots","41-33"),
  ("New England Patriots","Los Angeles Rams","13-3"),("Kansas City Chiefs","San Francisco 49ers","31-20"),
  ("Tampa Bay Buccaneers","Kansas City Chiefs","31-9"),("Los Angeles Rams","Cincinnati Bengals","23-20"),
  ("Kansas City Chiefs","Philadelphia Eagles","38-35"),("Kansas City Chiefs","San Francisco 49ers","25-22"),
  ("Philadelphia Eagles","Kansas City Chiefs","40-22"),("Seattle Seahawks","New England Patriots","29-13")]
_MVP={1957:[("Jim Brown","Cleveland Browns")],1958:[("Jim Brown","Cleveland Browns")],1959:[("Johnny Unitas","Baltimore Colts")],
  1961:[("Paul Hornung","Green Bay Packers")],1962:[("Jim Taylor","Green Bay Packers")],1963:[("Y. A. Tittle","New York Giants")],
  1964:[("Johnny Unitas","Baltimore Colts")],1965:[("Jim Brown","Cleveland Browns")],1966:[("Bart Starr","Green Bay Packers")],
  1967:[("Johnny Unitas","Baltimore Colts")],1968:[("Earl Morrall","Baltimore Colts")],1969:[("Roman Gabriel","Los Angeles Rams")],
  1970:[("John Brodie","San Francisco 49ers")],1971:[("Alan Page","Minnesota Vikings")],1972:[("Larry Brown","Washington")],
  1973:[("O. J. Simpson","Buffalo Bills")],1974:[("Ken Stabler","Oakland Raiders")],1975:[("Fran Tarkenton","Minnesota Vikings")],
  1976:[("Bert Jones","Baltimore Colts")],1977:[("Walter Payton","Chicago Bears")],1978:[("Terry Bradshaw","Pittsburgh Steelers")],
  1979:[("Earl Campbell","Houston Oilers")],1980:[("Brian Sipe","Cleveland Browns")],1981:[("Ken Anderson","Cincinnati Bengals")],
  1982:[("Mark Moseley","Washington")],1983:[("Joe Theismann","Washington")],1984:[("Dan Marino","Miami Dolphins")],
  1985:[("Marcus Allen","Los Angeles Raiders")],1986:[("Lawrence Taylor","New York Giants")],1987:[("John Elway","Denver Broncos")],
  1988:[("Boomer Esiason","Cincinnati Bengals")],1989:[("Joe Montana","San Francisco 49ers")],1990:[("Joe Montana","San Francisco 49ers")],
  1991:[("Thurman Thomas","Buffalo Bills")],1992:[("Steve Young","San Francisco 49ers")],1993:[("Emmitt Smith","Dallas Cowboys")],
  1994:[("Steve Young","San Francisco 49ers")],1995:[("Brett Favre","Green Bay Packers")],1996:[("Brett Favre","Green Bay Packers")],
  1997:[("Brett Favre","Green Bay Packers"),("Barry Sanders","Detroit Lions")],1998:[("Terrell Davis","Denver Broncos")],
  1999:[("Kurt Warner","St. Louis Rams")],2000:[("Marshall Faulk","St. Louis Rams")],2001:[("Kurt Warner","St. Louis Rams")],
  2002:[("Rich Gannon","Oakland Raiders")],2003:[("Peyton Manning","Indianapolis Colts"),("Steve McNair","Tennessee Titans")],
  2004:[("Peyton Manning","Indianapolis Colts")],2005:[("Shaun Alexander","Seattle Seahawks")],2006:[("LaDainian Tomlinson","San Diego Chargers")],
  2007:[("Tom Brady","New England Patriots")],2008:[("Peyton Manning","Indianapolis Colts")],2009:[("Peyton Manning","Indianapolis Colts")],
  2010:[("Tom Brady","New England Patriots")],2011:[("Aaron Rodgers","Green Bay Packers")],2012:[("Adrian Peterson","Minnesota Vikings")],
  2013:[("Peyton Manning","Denver Broncos")],2014:[("Aaron Rodgers","Green Bay Packers")],2015:[("Cam Newton","Carolina Panthers")],
  2016:[("Matt Ryan","Atlanta Falcons")],2017:[("Tom Brady","New England Patriots")],2018:[("Patrick Mahomes","Kansas City Chiefs")],
  2019:[("Lamar Jackson","Baltimore Ravens")],2020:[("Aaron Rodgers","Green Bay Packers")],2021:[("Aaron Rodgers","Green Bay Packers")],
  2022:[("Patrick Mahomes","Kansas City Chiefs")],2023:[("Lamar Jackson","Baltimore Ravens")],2024:[("Josh Allen","Buffalo Bills")],
  2025:[("Matthew Stafford","Los Angeles Rams")]}
HIST_NFL=[]
for (t,c,s,f) in _PRE:
    y=int(t); fin=("Juego de campeonato: "+f) if f else "Por récord de la temporada"
    HIST_NFL.append((t,c,s,fin,_MVP.get(y,[]),None))
for i,(c,s,f) in enumerate(_SBR):
    y=1966+i; HIST_NFL.append((str(y),c,s,f"Super Bowl {_SB[i]}: {f}",_MVP.get(y,[]),None))

# Premios de AP por temporada: año -> (jugador, equipo). Fuente: Wikipedia "AP NFL Offensive/Defensive
# Player of the Year" (cada año respaldado por la nota de AP de esa fecha; lista de ganadores múltiples coherente).
_OPOY={1972:("Larry Brown","Washington"),1973:("O. J. Simpson","Buffalo Bills"),1974:("Ken Stabler","Oakland Raiders"),
 1975:("Fran Tarkenton","Minnesota Vikings"),1976:("Bert Jones","Baltimore Colts"),1977:("Walter Payton","Chicago Bears"),
 1978:("Earl Campbell","Houston Oilers"),1979:("Earl Campbell","Houston Oilers"),1980:("Earl Campbell","Houston Oilers"),
 1981:("Ken Anderson","Cincinnati Bengals"),1982:("Dan Fouts","San Diego Chargers"),1983:("Joe Theismann","Washington"),
 1984:("Dan Marino","Miami Dolphins"),1985:("Marcus Allen","Los Angeles Raiders"),1986:("Eric Dickerson","Los Angeles Rams"),
 1987:("Jerry Rice","San Francisco 49ers"),1988:("Roger Craig","San Francisco 49ers"),1989:("Joe Montana","San Francisco 49ers"),
 1990:("Warren Moon","Houston Oilers"),1991:("Thurman Thomas","Buffalo Bills"),1992:("Steve Young","San Francisco 49ers"),
 1993:("Jerry Rice","San Francisco 49ers"),1994:("Barry Sanders","Detroit Lions"),1995:("Brett Favre","Green Bay Packers"),
 1996:("Terrell Davis","Denver Broncos"),1997:("Barry Sanders","Detroit Lions"),1998:("Terrell Davis","Denver Broncos"),
 1999:("Marshall Faulk","St. Louis Rams"),2000:("Marshall Faulk","St. Louis Rams"),2001:("Marshall Faulk","St. Louis Rams"),
 2002:("Priest Holmes","Kansas City Chiefs"),2003:("Jamal Lewis","Baltimore Ravens"),2004:("Peyton Manning","Indianapolis Colts"),
 2005:("Shaun Alexander","Seattle Seahawks"),2006:("LaDainian Tomlinson","San Diego Chargers"),2007:("Tom Brady","New England Patriots"),
 2008:("Drew Brees","New Orleans Saints"),2009:("Chris Johnson","Tennessee Titans"),2010:("Tom Brady","New England Patriots"),
 2011:("Drew Brees","New Orleans Saints"),2012:("Adrian Peterson","Minnesota Vikings"),2013:("Peyton Manning","Denver Broncos"),
 2014:("DeMarco Murray","Dallas Cowboys"),2015:("Cam Newton","Carolina Panthers"),2016:("Matt Ryan","Atlanta Falcons"),
 2017:("Todd Gurley","Los Angeles Rams"),2018:("Patrick Mahomes","Kansas City Chiefs"),2019:("Michael Thomas","New Orleans Saints"),
 2020:("Derrick Henry","Tennessee Titans"),2021:("Cooper Kupp","Los Angeles Rams"),2022:("Justin Jefferson","Minnesota Vikings"),
 2023:("Christian McCaffrey","San Francisco 49ers"),2024:("Saquon Barkley","Philadelphia Eagles"),2025:("Jaxon Smith-Njigba","Seattle Seahawks")}
_DPOY={1971:("Alan Page","Minnesota Vikings"),1972:("Joe Greene","Pittsburgh Steelers"),1973:("Dick Anderson","Miami Dolphins"),
 1974:("Joe Greene","Pittsburgh Steelers"),1975:("Mel Blount","Pittsburgh Steelers"),1976:("Jack Lambert","Pittsburgh Steelers"),
 1977:("Harvey Martin","Dallas Cowboys"),1978:("Randy Gradishar","Denver Broncos"),1979:("Lee Roy Selmon","Tampa Bay Buccaneers"),
 1980:("Lester Hayes","Oakland Raiders"),1981:("Lawrence Taylor","New York Giants"),1982:("Lawrence Taylor","New York Giants"),
 1983:("Doug Betters","Miami Dolphins"),1984:("Kenny Easley","Seattle Seahawks"),1985:("Mike Singletary","Chicago Bears"),
 1986:("Lawrence Taylor","New York Giants"),1987:("Reggie White","Philadelphia Eagles"),1988:("Mike Singletary","Chicago Bears"),
 1989:("Keith Millard","Minnesota Vikings"),1990:("Bruce Smith","Buffalo Bills"),1991:("Pat Swilling","New Orleans Saints"),
 1992:("Cortez Kennedy","Seattle Seahawks"),1993:("Rod Woodson","Pittsburgh Steelers"),1994:("Deion Sanders","San Francisco 49ers"),
 1995:("Bryce Paup","Buffalo Bills"),1996:("Bruce Smith","Buffalo Bills"),1997:("Dana Stubblefield","San Francisco 49ers"),
 1998:("Reggie White","Green Bay Packers"),1999:("Warren Sapp","Tampa Bay Buccaneers"),2000:("Ray Lewis","Baltimore Ravens"),
 2001:("Michael Strahan","New York Giants"),2002:("Derrick Brooks","Tampa Bay Buccaneers"),2003:("Ray Lewis","Baltimore Ravens"),
 2004:("Ed Reed","Baltimore Ravens"),2005:("Brian Urlacher","Chicago Bears"),2006:("Jason Taylor","Miami Dolphins"),
 2007:("Bob Sanders","Indianapolis Colts"),2008:("James Harrison","Pittsburgh Steelers"),2009:("Charles Woodson","Green Bay Packers"),
 2010:("Troy Polamalu","Pittsburgh Steelers"),2011:("Terrell Suggs","Baltimore Ravens"),2012:("J. J. Watt","Houston Texans"),
 2013:("Luke Kuechly","Carolina Panthers"),2014:("J. J. Watt","Houston Texans"),2015:("J. J. Watt","Houston Texans"),
 2016:("Khalil Mack","Oakland Raiders"),2017:("Aaron Donald","Los Angeles Rams"),2018:("Aaron Donald","Los Angeles Rams"),
 2019:("Stephon Gilmore","New England Patriots"),2020:("Aaron Donald","Los Angeles Rams"),2021:("T. J. Watt","Pittsburgh Steelers"),
 2022:("Nick Bosa","San Francisco 49ers"),2023:("Myles Garrett","Cleveland Browns"),2024:("Patrick Surtain II","Denver Broncos"),
 2025:("Myles Garrett","Cleveland Browns")}
# Premios por temporada en el orden en que se muestran: [etiqueta, jugador, equipo]
AW_NFL={}
for lbl,dd in [("Jugador Ofensivo del Año",_OPOY),("Jugador Defensivo del Año",_DPOY)]:
    for y,(p,t) in dd.items(): AW_NFL.setdefault(str(y),[]).append([lbl,p,t])

HISTORIA = {"mx": HIST_MX, "nfl": HIST_NFL}
HIST_AW = {"nfl": AW_NFL}  # premios extra por temporada (se muestran debajo del MVP)
out['historia']={k:[{"t":t,"c":c,"s":s,"f":f,"g":[list(x) for x in g],"n":n,"a":HIST_AW.get(k,{}).get(t,[])} for (t,c,s,f,g,n) in v] for k,v in HISTORIA.items()}
# Selección mexicana: palmarés y récords (datos fijos). Fuentes: Wikipedia "Mexico national football
# team" y "... records and statistics" (al 5 jul 2026), cruzado con Récord / Mediotiempo para los goles
# de Raúl Jiménez (48 oficiales FIFA; 49 contando el de Martinica). Actualizar a mano.
SEL_HIST = {
  "al": "5 de julio de 2026",
  "titulos": [  # [competición, [años]] — títulos oficiales (FIFA o confederación)
    ["Copa Oro / Campeonato de Concacaf", [1965, 1971, 1977, 1993, 1996, 1998, 2003, 2009, 2011, 2015, 2019, 2023, 2025]],
    ["Copa Confederaciones", [1999]],
    ["Nations League de Concacaf", [2025]],
    ["Copa Concacaf", [2015]],
    ["Campeonato NAFC", [1947, 1949]],
  ],
  "otros": [  # otros títulos de la selección mayor
    ["Copa de Naciones de Norteamérica", [1991]],
    ["Juegos Centroamericanos y del Caribe", [1935, 1938]],
  ],
  "resultados": [  # mejores resultados sin título
    ["Mundial", "Cuartos de final (1970 y 1986)"],
    ["Copa América", "Subcampeón (1993 y 2001)"],
    ["Juegos Olímpicos (Sub-23)", "Medalla de oro (Londres 2012)"],
  ],
  "goleadores": [  # [jugador, goles, años]
    ["Javier Hernández", 52, "2009–2019"], ["Raúl Jiménez", 48, "2013–"], ["Jared Borgetti", 46, "1997–2008"],
    ["Cuauhtémoc Blanco", 38, "1995–2014"], ["Luis Hernández", 35, "1995–2002"], ["Carlos Hermosillo", 34, "1984–1997"],
    ["Enrique Borja", 31, "1966–1975"],
  ],
  "partidos": [  # [jugador, partidos, años]
    ["Andrés Guardado", 180, "2005–2024"], ["Claudio Suárez", 178, "1992–2006"], ["Guillermo Ochoa", 153, "2005–2026"],
    ["Pável Pardo", 147, "1996–2009"], ["Rafael Márquez", 147, "1997–2018"], ["Gerardo Torrado", 144, "1999–2013"],
    ["Héctor Moreno", 132, "2007–2023"], ["Jorge Campos", 129, "1991–2003"], ["Raúl Jiménez", 128, "2013–"],
    ["Jesús Gallardo", 126, "2016–"],
  ],
  "equipo": [  # [récord, valor]
    ["Mundiales jugados", "18 (desde Uruguay 1930)"],
    ["Mejor lugar en el ranking FIFA", "4º (1998, 2003, 2004 y 2006)"],
    ["Mayor goleada a favor", "México 13–0 Bahamas (Toluca, 1987)"],
    ["Peor derrota", "Inglaterra 8–0 México (Londres, 1961)"],
    ["Primer partido", "México 2–1 Guatemala (Ciudad de México, 1923)"],
    ["Historial contra Estados Unidos", "79 partidos: 38 ganados, 17 empates, 24 perdidos"],
    ["Mundial 2026", "Octavos de final: 4 ganados, 1 perdido (10 goles a favor, 3 en contra)"],
    ["Antonio Carbajal", "Primer jugador en disputar 5 Mundiales seguidos (1950–1966)"],
  ],
}
out['sel_hist']=SEL_HIST

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
# Ajustes del power ranking de fútbol, una sección por liga (la página escoge la de la liga activa)
out['ranking_fut']={k:RJ.get(k,{}) for k in ['ligamx','premier','laliga','seriea','bundesliga','ligue1']}
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
