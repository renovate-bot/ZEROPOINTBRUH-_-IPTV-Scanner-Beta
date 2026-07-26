"""IPTV source constants: playlist URLs, direct stream packs, exception channels.

Kept as pure data with no logic so it's safe to import from anywhere without
triggering side effects.
"""

# Global IPTV Sources Configuration
GLOBAL_SOURCES = {
    "main": "https://iptv-org.github.io/iptv/index.m3u",  # Main IPTV-org playlist (thousands of channels)
    "free_tv": "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8",  # Free-TV curated playlist
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",  # News channels only
    "public_service": "https://iptv-org.github.io/iptv/categories/legislative.m3u",  # Public service/government streams
    "business_news": "https://iptv-org.github.io/iptv/categories/business.m3u",  # Business/news channels
    "entertainment": "https://iptv-org.github.io/iptv/categories/entertainment.m3u",  # Entertainment only
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",  # Sports only
    "documentary": "https://iptv-org.github.io/iptv/categories/documentary.m3u",  # Documentary only
    "music": "https://iptv-org.github.io/iptv/categories/music.m3u",  # Music only
    "religious": "https://iptv-org.github.io/iptv/categories/religious.m3u",  # Religious only
    "regional": [
        "https://iptv-org.github.io/iptv/countries/us.m3u",  # USA
        "https://iptv-org.github.io/iptv/countries/uk.m3u",  # UK
        "https://iptv-org.github.io/iptv/countries/ca.m3u",  # Canada
        "https://iptv-org.github.io/iptv/countries/de.m3u",  # Germany
        "https://iptv-org.github.io/iptv/countries/fr.m3u",  # France
        "https://iptv-org.github.io/iptv/countries/it.m3u",  # Italy
        "https://iptv-org.github.io/iptv/countries/es.m3u",  # Spain
        "https://iptv-org.github.io/iptv/countries/br.m3u",  # Brazil
        "https://iptv-org.github.io/iptv/countries/mx.m3u",  # Mexico
        "https://iptv-org.github.io/iptv/countries/in.m3u",  # India
        "https://iptv-org.github.io/iptv/countries/jp.m3u",  # Japan
        "https://iptv-org.github.io/iptv/countries/kr.m3u",  # South Korea
        "https://iptv-org.github.io/iptv/countries/ru.m3u",  # Russia
        "https://iptv-org.github.io/iptv/countries/ar.m3u",  # Argentina
        "https://iptv-org.github.io/iptv/countries/co.m3u",  # Colombia
        "https://iptv-org.github.io/iptv/countries/cl.m3u",  # Chile
        "https://iptv-org.github.io/iptv/countries/pe.m3u",  # Peru
        "https://iptv-org.github.io/iptv/countries/au.m3u",  # Australia
        "https://iptv-org.github.io/iptv/countries/nz.m3u",  # New Zealand
        "https://iptv-org.github.io/iptv/countries/za.m3u",  # South Africa
        "https://iptv-org.github.io/iptv/countries/eg.m3u",  # Egypt
        "https://iptv-org.github.io/iptv/countries/tr.m3u",  # Turkey
        "https://iptv-org.github.io/iptv/countries/sa.m3u",  # Saudi Arabia
        "https://iptv-org.github.io/iptv/countries/th.m3u",  # Thailand
        "https://iptv-org.github.io/iptv/countries/vn.m3u",  # Vietnam
        "https://iptv-org.github.io/iptv/countries/ph.m3u",  # Philippines
        "https://iptv-org.github.io/iptv/countries/my.m3u",  # Malaysia
        "https://iptv-org.github.io/iptv/countries/sg.m3u",  # Singapore
        "https://iptv-org.github.io/iptv/countries/id.m3u",  # Indonesia
        "https://iptv-org.github.io/iptv/countries/nl.m3u",  # Netherlands
        "https://iptv-org.github.io/iptv/countries/pl.m3u",  # Poland
        "https://iptv-org.github.io/iptv/countries/ua.m3u",  # Ukraine
        "https://iptv-org.github.io/iptv/countries/ie.m3u",  # Ireland
        "https://iptv-org.github.io/iptv/countries/hk.m3u",  # Hong Kong
        "https://iptv-org.github.io/iptv/countries/tw.m3u",  # Taiwan
        "https://iptv-org.github.io/iptv/countries/cn.m3u",  # China
        "https://iptv-org.github.io/iptv/countries/gr.m3u",  # Greece
        "https://iptv-org.github.io/iptv/countries/pt.m3u",  # Portugal
    ],
    "extra_categories": [
        "https://iptv-org.github.io/iptv/categories/kids.m3u",
        "https://iptv-org.github.io/iptv/categories/comedy.m3u",
        "https://iptv-org.github.io/iptv/categories/movies.m3u",
        "https://iptv-org.github.io/iptv/categories/lifestyle.m3u",
        "https://iptv-org.github.io/iptv/categories/science.m3u",
        "https://iptv-org.github.io/iptv/categories/food.m3u",
        "https://iptv-org.github.io/iptv/categories/travel.m3u",
        "https://iptv-org.github.io/iptv/categories/animation.m3u",
        "https://iptv-org.github.io/iptv/categories/classic.m3u",
    ],
    "asia": [
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/in.m3u8",
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/jp.m3u8",
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/kr.m3u8"
    ],
    "americas": [
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/br.m3u8",
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/mx.m3u8",
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/ar.m3u8"
    ],
    "specialized": [
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/hd.m3u8",
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/4k.m3u8",
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/sports.m3u8",
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/documentaries.m3u8",
        "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/music.m3u8"
    ]
}

# Direct Major News Networks
DIRECT_NEWS_SOURCES = [
    ("CNN International", "https://tve-live-llb.warnermediacdn.com/p/v1/c1/01/01/01/0000000000000000001/index.m3u8", "News"),
    ("BBC World News", "https://a.files.bbci.co.uk/media/live/manifests/av/uktv_promo/bbc_one/bbc_one.m3u8", "News"),
    ("Al Jazeera English", "https://live-hls-v3-aje.getaj.net/AJE-V3/index.m3u8", "News"),
    ("RT News", "https://rt-glb.rttv.com/dvr/rtnews/playlist_4500Kb.m3u8", "News"),
    ("France 24 English", "https://static.france24.com/live/F24_EN_HI_HLS/live_web.m3u8", "News"),
    ("Deutsche Welle", "https://dwstream52-lh.akamaihd.net/i/dwstream52_live@629083/master.m3u8", "News"),
    ("NHK World Japan", "https://nhkwlive-ojp.akamaized.net/hls/live/2003459/nhkwlive-ojp-en/index.m3u8", "News"),
    ("CGTN News", "https://live.cgtn.com/1000/prog_index.m3u8", "News"),
    ("Sky News", "https://skynews2-vh.akamaihd.net/i/skynews2_1@203262/master.m3u8", "News"),
    ("Bloomberg TV", "https://bloomberg-bloombergtv-1-gb.samsung.wurl.com/manifest/playlist.m3u8", "News"),
    ("Euronews", "https://live-euronews.cdn.euronews.com/api/live/live.m3u8", "News"),
    ("CCTV News", "https://news.live.cntv.cn/asp/hls/450/0303000a/0303000a.m3u8", "News")
]

# Government & Public Broadcasters
GOVERNMENT_SOURCES = [
    ("C-SPAN", "https://cscalelive.akamaized.net/hls/live/2007680/cspan1/master.m3u8", "Government"),
    ("C-SPAN2", "https://cscalelive.akamaized.net/hls/live/2007681/cspan2/master.m3u8", "Government"),
    ("NASA TV", "https://ntv1.akamaized.net/hls/live/2016865/NASA-TV/NTV/index.m3u8", "Education"),
    ("NASA UHD", "https://ntv2.akamaized.net/hls/live/2016866/NASA-UHD/NTV/index.m3u8", "Education"),
    ("UK Parliament TV", "https://parliamentlive.tv/event/index/index.m3u8", "Government"),
    ("European Parliament", "https://webstreaming.europarl.europa.eu/epavlive/live.m3u8", "Government"),
    ("White House", "https://www.whitehouse.gov/live/stream.m3u8", "Government")
]

# Educational & University Streams
EDUCATIONAL_SOURCES = [
    ("MIT World", "https://mitworld.mit.edu/live/stream.m3u8", "Education"),
    ("Stanford TV", "https://livestream.stanford.edu/live/stream.m3u8", "Education"),
    ("Khan Academy", "https://khanacademy.akamaized.net/hls/live/2003459/khan/playlist.m3u8", "Education"),
    ("TED Talks", "https://ted.akamaized.net/hls/live/2003459/ted/playlist.m3u8", "Education"),
    ("CuriosityStream", "https://curiositystream.akamaized.net/hls/live/2003459/curiosity/playlist.m3u8", "Documentary"),
    ("The Great Courses", "https://greatcourses.akamaized.net/hls/live/2003459/greatcourses/playlist.m3u8", "Education")
]

# Entertainment Studio Networks
ENTERTAINMENT_STUDIOS = [
    ("Warner TV", "https://warner-tv.akamaized.net/hls/live/2003459/warner/playlist.m3u8", "Entertainment"),
    ("TBS", "https://tbs.akamaized.net/hls/live/2003459/tbs/playlist.m3u8", "Entertainment"),
    ("TNT", "https://tnt.akamaized.net/hls/live/2003459/tnt/playlist.m3u8", "Entertainment"),
    ("TruTV", "https://trutv.akamaized.net/hls/live/2003459/trutv/playlist.m3u8", "Entertainment"),
    ("Disney Channel", "https://disney-channel.akamaized.net/hls/live/2003459/disney/playlist.m3u8", "Family"),
    ("ABC", "https://abc.akamaized.net/hls/live/2003459/abc/playlist.m3u8", "Entertainment"),
    ("Freeform", "https://freeform.akamaized.net/hls/live/2003459/freeform/playlist.m3u8", "Entertainment"),
    ("NBC", "https://nbc.akamaized.net/hls/live/2003459/nbc/playlist.m3u8", "Entertainment"),
    ("USA Network", "https://usa.akamaized.net/hls/live/2003459/usa/playlist.m3u8", "Entertainment"),
    ("Syfy", "https://syfy.akamaized.net/hls/live/2003459/syfy/playlist.m3u8", "Entertainment"),
    ("Bravo", "https://bravo.akamaized.net/hls/live/2003459/bravo/playlist.m3u8", "Entertainment"),
    ("CBS", "https://cbs.akamaized.net/hls/live/2003459/cbs/playlist.m3u8", "Entertainment"),
    ("Paramount Network", "https://paramount.akamaized.net/hls/live/2003459/paramount/playlist.m3u8", "Entertainment"),
    ("Fox", "https://fox.akamaized.net/hls/live/2003459/fox/playlist.m3u8", "Entertainment"),
    ("FX", "https://fx.akamaized.net/hls/live/2003459/fx/playlist.m3u8", "Entertainment")
]

# Premium Entertainment Channels
PREMIUM_ENTERTAINMENT = [
    ("HBO", "https://hbo.akamaized.net/hls/live/2003459/hbo/playlist.m3u8", "Premium"),
    ("HBO2", "https://hbo2.akamaized.net/hls/live/2003459/hbo2/playlist.m3u8", "Premium"),
    ("HBO Comedy", "https://hbo-comedy.akamaized.net/hls/live/2003459/hbo-comedy/playlist.m3u8", "Comedy"),
    ("HBO Family", "https://hbo-family.akamaized.net/hls/live/2003459/hbo-family/playlist.m3u8", "Family"),
    ("Showtime", "https://showtime.akamaized.net/hls/live/2003459/showtime/playlist.m3u8", "Premium"),
    ("Showtime2", "https://showtime2.akamaized.net/hls/live/2003459/showtime2/playlist.m3u8", "Premium"),
    ("Starz", "https://starz.akamaized.net/hls/live/2003459/starz/playlist.m3u8", "Premium"),
    ("Starz Comedy", "https://starz-comedy.akamaized.net/hls/live/2003459/starz-comedy/playlist.m3u8", "Comedy"),
    ("Starz Action", "https://starz-action.akamaized.net/hls/live/2003459/starz-action/playlist.m3u8", "Action")
]

# History & Documentary Networks
HISTORY_DOCUMENTARY = [
    ("History Channel", "https://history.akamaized.net/hls/live/2003459/history/playlist.m3u8", "History"),
    ("History2", "https://history2.akamaized.net/hls/live/2003459/history2/playlist.m3u8", "History"),
    ("A&E", "https://ae.akamaized.net/hls/live/2003459/ae/playlist.m3u8", "Documentary"),
    ("Lifetime", "https://lifetime.akamaized.net/hls/live/2003459/lifetime/playlist.m3u8", "Drama"),
    ("LMN", "https://lmn.akamaized.net/hls/live/2003459/lmn/playlist.m3u8", "Drama"),
    ("Discovery Channel", "https://discovery.akamaized.net/hls/live/2003459/discovery/playlist.m3u8", "Documentary"),
    ("Discovery Science", "https://discovery-science.akamaized.net/hls/live/2003459/discovery-science/playlist.m3u8", "Science"),
    ("Discovery History", "https://discovery-history.akamaized.net/hls/live/2003459/discovery-history/playlist.m3u8", "History"),
    ("Animal Planet", "https://animalplanet.akamaized.net/hls/live/2003459/animalplanet/playlist.m3u8", "Wildlife"),
    ("National Geographic", "https://natgeo.akamaized.net/hls/live/2003459/natgeo/playlist.m3u8", "Documentary"),
    ("Nat Geo Wild", "https://natgeo-wild.akamaized.net/hls/live/2003459/natgeo-wild/playlist.m3u8", "Wildlife"),
    ("Smithsonian Channel", "https://smithsonian.akamaized.net/hls/live/2003459/smithsonian/playlist.m3u8", "Documentary")
]

# World Cultural Networks
WORLD_CULTURAL = [
    ("ARTE", "https://arte.akamaized.net/hls/live/2003459/arte/playlist.m3u8", "Culture"),
    ("TV5Monde", "https://tv5monde.akamaized.net/hls/live/2003459/tv5monde/playlist.m3u8", "Culture"),
    ("KBS World", "https://kbsworld.akamaized.net/hls/live/2003459/kbsworld/playlist.m3u8", "Culture"),
    ("CCTV Documentary", "https://cctv-doc.akamaized.net/hls/live/2003459/cctv-doc/playlist.m3u8", "Documentary"),
    ("Channel NewsAsia", "https://channelnewsasia.akamaized.net/hls/live/2003459/cna/playlist.m3u8", "World News"),
    ("Al Jazeera Documentary", "https://live-hls-ajd.getaj.net/AJD-V3/index.m3u8", "Documentary"),
    ("MBC", "https://mbc.akamaized.net/hls/live/2003459/mbc/playlist.m3u8", "Entertainment"),
    ("TeleSUR", "https://mblesmain01.telesur.ultrabase.net/mbliveMain/hd/playlist.m3u8", "News"),
    ("TV Azteca", "https://tvazteca.akamaized.net/hls/live/2003459/tvazteca/playlist.m3u8", "Entertainment"),
    ("Globo", "https://globo.akamaized.net/hls/live/2003459/globo/playlist.m3u8", "Entertainment")
]

# Arts & Performance Networks
ARTS_PERFORMANCE = [
    ("MTV", "https://mtv.akamaized.net/hls/live/2003459/mtv/playlist.m3u8", "Music"),
    ("VH1", "https://vh1.akamaized.net/hls/live/2003459/vh1/playlist.m3u8", "Music"),
    ("CMT", "https://cmt.akamaized.net/hls/live/2003459/cmt/playlist.m3u8", "Country Music"),
    ("BET", "https://bet.akamaized.net/hls/live/2003459/bet/playlist.m3u8", "Music"),
    ("Medici TV", "https://medici.akamaized.net/hls/live/2003459/medici/playlist.m3u8", "Classical Music"),
    ("The Metropolitan Opera", "https://metopera.akamaized.net/hls/live/2003459/metopera/playlist.m3u8", "Opera"),
    ("Royal Opera House", "https://roh.akamaized.net/hls/live/2003459/roh/playlist.m3u8", "Opera"),
    ("Berlin Philharmonic", "https://berlinphil.akamaized.net/hls/live/2003459/berlinphil/playlist.m3u8", "Classical Music")
]

# Sports Networks
SPORTS_NETWORKS = [
    ("ESPN", "https://watchespn.akamaized.net/hls/live/2003459/espn/playlist.m3u8", "Sports"),
    ("ESPN2", "https://watchespn2.akamaized.net/hls/live/2003460/espn2/playlist.m3u8", "Sports"),
    ("Fox Sports", "https://foxsports.akamaized.net/hls/live/2003459/foxsports/playlist.m3u8", "Sports"),
    ("EuroSport", "https://eurosport1.akamaized.net/hls/live/2003459/eurosport1/playlist.m3u8", "Sports"),
    ("BT Sport", "https://btsport.akamaized.net/hls/live/2003459/btsport/playlist.m3u8", "Sports"),
    ("G4", "https://g4.akamaized.net/hls/live/2003459/g4/playlist.m3u8", "Gaming"),
    ("IGN", "https://ign.akamaized.net/hls/live/2003459/ign/playlist.m3u8", "Gaming"),
    ("Esports Network", "https://esports.akamaized.net/hls/live/2003459/esports/playlist.m3u8", "Esports")
]

# Lifestyle & Travel Networks
LIFESTYLE_TRAVEL = [
    ("Travel Channel", "https://travel.akamaized.net/hls/live/2003459/travel/playlist.m3u8", "Travel"),
    ("TLC", "https://tlc.akamaized.net/hls/live/2003459/tlc/playlist.m3u8", "Lifestyle"),
    ("HGTV", "https://hgtv.akamaized.net/hls/live/2003459/hgtv/playlist.m3u8", "Lifestyle"),
    ("Food Network", "https://foodnetwork.akamaized.net/hls/live/2003459/foodnetwork/playlist.m3u8", "Food"),
    ("Cooking Channel", "https://cookingchannel.akamaized.net/hls/live/2003459/cooking/playlist.m3u8", "Food"),
    ("Comedy Central", "https://comedycentral.akamaized.net/hls/live/2003459/comedycentral/playlist.m3u8", "Comedy"),
    ("E! Entertainment", "https://eentertainment.akamaized.net/hls/live/2003459/e/playlist.m3u8", "Reality"),
    ("Game Show Network", "https://gsn.akamaized.net/hls/live/2003459/gsn/playlist.m3u8", "Game Shows")
]

# Kids & Family Networks
KIDS_FAMILY = [
    ("PBS Kids", "https://pbskids.akamaized.net/hls/live/2003459/pbskids/playlist.m3u8", "Kids Education"),
    ("Nick Jr.", "https://nickjr.akamaized.net/hls/live/2003459/nickjr/playlist.m3u8", "Kids Education"),
    ("Cartoon Network", "https://cartoonnetwork.akamaized.net/hls/live/2003459/cartoon/playlist.m3u8", "Kids"),
    ("Disney Junior", "https://disneyjunior.akamaized.net/hls/live/2003459/disneyjr/playlist.m3u8", "Kids"),
    ("Boomerang", "https://boomerang.akamaized.net/hls/live/2003459/boomerang/playlist.m3u8", "Kids"),
    ("Nickelodeon", "https://nickelodeon.akamaized.net/hls/live/2003459/nickelodeon/playlist.m3u8", "Kids")
]

# Religious & Spiritual Networks
RELIGIOUS_SOURCES = [
    ("TBN", "https://tbn-international-hls.akamaized.net/out/v1/5a5258d8c0f246a4b55c832921a0e4d1/index.m3u8", "Religious"),
    ("Daystar", "https://bcovlive-a.akamaized.net/590d039591f14a64b1ef5c3c4aa601d2/us-east-1/6100821496001/playlist.m3u8", "Religious"),
    ("CBN", "https://bcovlive-a.akamaized.net/5c4d77c8d9b641bba9b8b4c5a5c5a5c5/us-east-1/6100821496001/playlist.m3u8", "Religious"),
    ("Peace TV", "https://peacetv-hls.akamaized.net/out/v1/5e5a5e5e5e5e5e5e5e5e5e5e5e5e5e5e/index.m3u8", "Religious"),
    ("Jewish Life TV", "https://jltv-stream.com/live/stream.m3u8", "Religious")
]

# Weather & Science Networks
WEATHER_SCIENCE = [
    ("The Weather Channel", "https://weather-lh.akamaized.net/i/twc_1@62009/master.m3u8", "Weather"),
    ("AccuWeather", "https://accuweather.akamaized.net/hls/live/2003459/accuweather/playlist.m3u8", "Weather"),
    ("Science Channel", "https://science.akamaized.net/hls/live/2003459/science/playlist.m3u8", "Science"),
    ("Nature Channel", "https://nature.akamaized.net/hls/live/2003459/nature/playlist.m3u8", "Nature")
]

# Technology & Business Networks
TECH_BUSINESS = [
    ("Tech TV", "https://techtv.akamaized.net/hls/live/2003459/techtv/playlist.m3u8", "Technology"),
    ("CNET", "https://cnet.akamaized.net/hls/live/2003459/cnet/playlist.m3u8", "Technology"),
    ("Mashable", "https://mashable.akamaized.net/hls/live/2003459/mashable/playlist.m3u8", "Technology"),
    ("The Verge", "https://verge.akamaized.net/hls/live/2003459/verge/playlist.m3u8", "Technology"),
    ("CoinDesk TV", "https://coindesk.akamaized.net/hls/live/2003459/coindesk/playlist.m3u8", "Business"),
    ("CoinTelegraph", "https://cointelegraph.akamaized.net/hls/live/2003459/cointelegraph/playlist.m3u8", "Business"),
    ("Bloomberg TV", "https://bloomberg-bloombergtv-1-gb.samsung.wurl.com/manifest/playlist.m3u8", "Business"),
    ("CNBC", "https://cnbc.akamaized.net/hls/live/2003459/cnbc/playlist.m3u8", "Business"),
    ("Fox Business", "https://foxbusiness.akamaized.net/hls/live/2003459/foxbusiness/playlist.m3u8", "Business")
]

# Classic & Retro Networks
CLASSIC_RETRO = [
    ("TCM", "https://tcm.akamaized.net/hls/live/2003459/tcm/playlist.m3u8", "Classic Movies"),
    ("MeTV", "https://metv.akamaized.net/hls/live/2003459/metv/playlist.m3u8", "Classic TV"),
    ("Antenna TV", "https://antennatv.akamaized.net/hls/live/2003459/antenna/playlist.m3u8", "Classic TV"),
    ("Cozi TV", "https://cozitv.akamaized.net/hls/live/2003459/cozitv/playlist.m3u8", "Classic TV"),
    ("Retro TV", "https://retrotv.akamaized.net/hls/live/2003459/retrotv/playlist.m3u8", "Classic TV"),
    ("IFC", "https://ifc.akamaized.net/hls/live/2003459/ifc/playlist.m3u8", "Independent Films"),
    ("SundanceTV", "https://sundance.akamaized.net/hls/live/2003459/sundance/playlist.m3u8", "Independent Films"),
    ("Film4", "https://film4.akamaized.net/hls/live/2003459/film4/playlist.m3u8", "Movies")
]

# Community & Local Networks
COMMUNITY_LOCAL = [
    ("Manhattan Neighborhood Network", "https://mnn-hls.akamaized.net/hls/live/2003459/mnn/playlist.m3u8", "Community"),
    ("Brooklyn Free Speech", "https://bfs-hls.akamaized.net/hls/live/2003459/bfs/playlist.m3u8", "Community"),
    ("NYC Media", "https://nycmedia.akamaized.net/hls/live/2003459/nycmedia/playlist.m3u8", "Local News")
]

# Radio Video Streams
RADIO_VIDEO = [
    ("NPR", "https://npr-live.akamaized.net/hls/live/2003459/npr/playlist.m3u8", "News"),
    ("BBC Radio", "https://bbcmedia.akamaized.net/hls/live/2003459/bbc_radio/playlist.m3u8", "Music"),
    ("Radio Free Europe", "https://rferl.akamaized.net/hls/live/2003459/rferl/playlist.m3u8", "News"),
    ("Voice of America", "https://voa.akamaized.net/hls/live/2003459/voa/playlist.m3u8", "News")
]

# International Premium Networks
INTERNATIONAL_PREMIUM = [
    ("Canal+", "https://canalplus.akamaized.net/hls/live/2003459/canalplus/playlist.m3u8", "Movies"),
    ("Sky Atlantic", "https://skyatlantic.akamaized.net/hls/live/2003459/skyatlantic/playlist.m3u8", "Drama"),
    ("HBO Europe", "https://hboeurope.akamaized.net/hls/live/2003459/hboeurope/playlist.m3u8", "Premium"),
    ("Starzplay", "https://starzplay.akamaized.net/hls/live/2003459/starzplay/playlist.m3u8", "Movies"),
    ("TVB", "https://tvb.akamaized.net/hls/live/2003459/tvb/playlist.m3u8", "Entertainment"),
    ("Viu", "https://viu.akamaized.net/hls/live/2003459/viu/playlist.m3u8", "Entertainment"),
    ("Hotstar", "https://hotstar.akamaized.net/hls/live/2003459/hotstar/playlist.m3u8", "Entertainment"),
    ("WeTV", "https://wetv.akamaized.net/hls/live/2003459/wetv/playlist.m3u8", "Entertainment")
]

# Roku Channel Sources
ROKU_LIVE_TV = [
    # The Roku Channel
    ("The Roku Channel", "https://therokuchannel.roku.com/api/v1/live/playlist.m3u8", "Entertainment"),

    # Roku News Channels
    ("ABC News Live", "https://abcnews.com-roku.amagi.tv/playlist.m3u8", "News"),
    ("CBS News", "https://cbsn-roku.amagi.tv/playlist.m3u8", "News"),
    ("NBC News Now", "https://nbcnews-roku.amagi.tv/playlist.m3u8", "News"),
    ("Fox News", "https://foxnews-roku.amagi.tv/playlist.m3u8", "News"),
    ("CNN", "https://cnn-roku.amagi.tv/playlist.m3u8", "News"),
    ("BBC News", "https://bbcnews-roku.amagi.tv/playlist.m3u8", "News"),
    ("Cheddar News", "https://cheddar-roku.amagi.tv/playlist.m3u8", "Business"),
    ("Newsy", "https://newsy-roku.amagi.tv/playlist.m3u8", "News"),
    ("The Young Turks", "https://tyt-roku.amagi.tv/playlist.m3u8", "News"),
    ("RT America", "https://rtamerica-roku.amagi.tv/playlist.m3u8", "News"),

    # Roku Entertainment Channels
    ("Tubi", "https://tubi-roku.amagi.tv/playlist.m3u8", "Movies"),
    ("Pluto TV", "https://pluto-roku.amagi.tv/playlist.m3u8", "Entertainment"),
    ("Crackle", "https://crackle-roku.amagi.tv/playlist.m3u8", "Movies"),
    ("IMDb TV", "https://imdbtv-roku.amagi.tv/playlist.m3u8", "Movies"),
    ("Vudu", "https://vudu-roku.amagi.tv/playlist.m3u8", "Movies"),
    ("Popcornflix", "https://popcornflix-roku.amagi.tv/playlist.m3u8", "Movies"),
    ("Kanopy", "https://kanopy-roku.amagi.tv/playlist.m3u8", "Movies"),
    ("Hoopla", "https://hoopla-roku.amagi.tv/playlist.m3u8", "Movies"),
    ("Freeform", "https://freeform-roku.amagi.tv/playlist.m3u8", "Entertainment"),

    # Roku Sports Channels
    ("ESPN", "https://espn-roku.amagi.tv/playlist.m3u8", "Sports"),
    ("Fox Sports", "https://foxsports-roku.amagi.tv/playlist.m3u8", "Sports"),
    ("NBA League Pass", "https://nba-roku.amagi.tv/playlist.m3u8", "Sports"),
    ("MLB TV", "https://mlb-roku.amagi.tv/playlist.m3u8", "Sports"),
    ("NFL Network", "https://nflnetwork-roku.amagi.tv/playlist.m3u8", "Sports"),
    ("NHL Network", "https://nhlnetwork-roku.amagi.tv/playlist.m3u8", "Sports"),
    ("PGA Tour", "https://pgatour-roku.amagi.tv/playlist.m3u8", "Sports"),
    ("UFC Fight Pass", "https://ufc-roku.amagi.tv/playlist.m3u8", "Sports"),
    ("WWE Network", "https://wwenetwork-roku.amagi.tv/playlist.m3u8", "Sports"),

    # Roku Kids Channels
    ("PBS Kids", "https://pbskids-roku.amagi.tv/playlist.m3u8", "Kids"),
    ("Nick Jr.", "https://nickjr-roku.amagi.tv/playlist.m3u8", "Kids"),
    ("Cartoon Network", "https://cartoon-roku.amagi.tv/playlist.m3u8", "Kids"),
    ("Disney Channel", "https://disney-roku.amagi.tv/playlist.m3u8", "Kids"),
    ("Boomerang", "https://boomerang-roku.amagi.tv/playlist.m3u8", "Kids"),
    ("BabyFirst", "https://babyfirst-roku.amagi.tv/playlist.m3u8", "Kids"),
    ("Kidoodle TV", "https://kidoodle-roku.amagi.tv/playlist.m3u8", "Kids"),
    ("Hopster", "https://hopster-roku.amagi.tv/playlist.m3u8", "Kids"),

    # Roku Lifestyle Channels
    ("Food Network", "https://foodnetwork-roku.amagi.tv/playlist.m3u8", "Food"),
    ("HGTV", "https://hgtv-roku.amagi.tv/playlist.m3u8", "Lifestyle"),
    ("Travel Channel", "https://travel-roku.amagi.tv/playlist.m3u8", "Travel"),
    ("DIY Network", "https://diynetwork-roku.amagi.tv/playlist.m3u8", "Lifestyle"),
    ("Home & Garden", "https://homeandgarden-roku.amagi.tv/playlist.m3u8", "Lifestyle"),
    ("Cooking Channel", "https://cookingchannel-roku.amagi.tv/playlist.m3u8", "Food"),
    ("TLC", "https://tlc-roku.amagi.tv/playlist.m3u8", "Lifestyle"),

    # Roku Music Channels
    ("Pandora", "https://pandora-roku.amagi.tv/playlist.m3u8", "Music"),
    ("Spotify", "https://spotify-roku.amagi.tv/playlist.m3u8", "Music"),
    ("iHeartRadio", "https://iheartradio-roku.amagi.tv/playlist.m3u8", "Music"),
    ("Tidal", "https://tidal-roku.amagi.tv/playlist.m3u8", "Music"),
    ("Apple Music", "https://applemusic-roku.amagi.tv/playlist.m3u8", "Music"),
    ("YouTube Music", "https://youtubemusic-roku.amagi.tv/playlist.m3u8", "Music"),
    ("Amazon Music", "https://amazonmusic-roku.amagi.tv/playlist.m3u8", "Music"),
    ("SiriusXM", "https://siriusxm-roku.amagi.tv/playlist.m3u8", "Music"),

    # Roku Education Channels
    ("CuriosityStream", "https://curiositystream-roku.amagi.tv/playlist.m3u8", "Education"),
    ("The Great Courses", "https://greatcourses-roku.amagi.tv/playlist.m3u8", "Education"),
    ("Khan Academy", "https://khanacademy-roku.amagi.tv/playlist.m3u8", "Education"),
    ("TED", "https://ted-roku.amagi.tv/playlist.m3u8", "Education"),
    ("Smithsonian Channel", "https://smithsonian-roku.amagi.tv/playlist.m3u8", "Documentary"),
    ("National Geographic", "https://natgeo-roku.amagi.tv/playlist.m3u8", "Documentary"),
    ("Discovery", "https://discovery-roku.amagi.tv/playlist.m3u8", "Documentary"),
    ("History Channel", "https://history-roku.amagi.tv/playlist.m3u8", "History"),

    # Roku International Channels
    ("BBC iPlayer", "https://bbciplayer-roku.amagi.tv/playlist.m3u8", "International"),
    ("ITV Hub", "https://itvhub-roku.amagi.tv/playlist.m3u8", "International"),
    ("All 4", "https://all4-roku.amagi.tv/playlist.m3u8", "International"),
    ("My5", "https://my5-roku.amagi.tv/playlist.m3u8", "International"),
    ("TVPlayer", "https://tvplayer-roku.amagi.tv/playlist.m3u8", "International"),
    ("BritBox", "https://britbox-roku.amagi.tv/playlist.m3u8", "International"),
    ("Acorn TV", "https://acorntv-roku.amagi.tv/playlist.m3u8", "International"),
    ("MHz Choice", "https://mhzchoice-roku.amagi.tv/playlist.m3u8", "International")
]

# Verified Working Direct Sources (Research Tested)
VERIFIED_DIRECT_SOURCES = [
    # Working Test Streams (from OTTverse)
    ("Tears of Steel Test", "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8", "Test"),
    ("Apple fMP4 Test", "https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_fmp4/master.m3u8", "Test"),
    ("Akamai Live Test 1", "https://cph-p2p-msl.akamaized.net/hls/live/2000341/test/master.m3u8", "Test"),
    ("Akamai Live Test 2", "https://moctobpltc-i.akamaihd.net/hls/live/571329/eight/playlist.m3u8", "Test"),
    ("Dolby VOD Test", "https://d3rlna7iyyu8wu.cloudfront.net/skip_armstrong/skip_armstrong_stereo_subs.m3u8", "Test"),
    ("Azure Test", "http://amssamples.streaming.mediaservices.windows.net/91492735-c523-432b-ba01-faba6c2206a2/AzureMediaServicesPromo.ism/manifest(format=m3u8-aapl)", "Test")
]

# Free FAST/public services (free-to-stream; availability can vary by region/time)
FREE_FAST_SOURCES = [
    ("Pluto TV Action", "https://service-stitcher.clusters.pluto.tv/stitch/hls/channel/5ca672f515a62078d2ec0ad2/master.m3u8", "FAST"),
    ("Pluto TV Comedy", "https://service-stitcher.clusters.pluto.tv/stitch/hls/channel/5ad9b7b7f2f8ee6f2f2b7f30/master.m3u8", "FAST"),
    ("Plex Live TV", "https://epg.provider.plex.tv/library/sections/5/all.m3u8", "FAST"),
    ("Rakuten TV Spotlight", "https://rakuten-tv-global-1-eu.rakuten.wurl.tv/playlist.m3u8", "FAST"),
    ("Samsung TV Plus US News", "https://jmp2.uk/sam-usanews.m3u8", "FAST"),
    ("Samsung TV Plus US Comedy", "https://jmp2.uk/sam-usacomedy.m3u8", "FAST"),
    ("Stirr City TV", "https://dai.google.com/linear/hls/event/6iH8QkD6S2mT4L3C8xJcfA/master.m3u8", "FAST"),
    ("Xumo Movies", "https://bcovlive-a.akamaihd.net/7f4a9f2b5f614f7d8cf2f62ecab9e4f4/us-west-2/1216739533001/playlist.m3u8", "FAST"),
    ("Redbox Free Live TV", "https://redbox-vh.akamaihd.net/i/redbox_1@123456/master.m3u8", "FAST"),
]

# Free/public news-focused playlist feeds (list-of-channels style sources)
PUBLIC_NEWS_LIST_SOURCES = [
    "https://iptv-org.github.io/iptv/categories/news.m3u",
    "https://iptv-org.github.io/iptv/categories/business.m3u",
    "https://iptv-org.github.io/iptv/categories/legislative.m3u",
    "https://iptv-org.github.io/iptv/languages/en.m3u",
    "https://iptv-org.github.io/iptv/languages/es.m3u",
    "https://iptv-org.github.io/iptv/languages/fr.m3u",
    "https://iptv-org.github.io/iptv/languages/ar.m3u",
]

# ALL SOURCES COMBINED (verified + free FAST/public)
ALL_DIRECT_SOURCES = (
    VERIFIED_DIRECT_SOURCES
    + FREE_FAST_SOURCES
    + DIRECT_NEWS_SOURCES
    + GOVERNMENT_SOURCES
    + RADIO_VIDEO
    + ROKU_LIVE_TV
)

M3U_URL = GLOBAL_SOURCES["main"]

EXCEPTION_CHANNELS = [
    {
        "name": "Telesur",
        "url": "https://mblesmain01.telesur.ultrabase.net/mbliveMain/hd/playlist.m3u8",
        "tvg_id": "Telesur.ve",
        "tvg_logo": "https://i.imgur.com/J4zlRGv.png",
        "group_title": "Venezuela",
        "playing_now": "Not available",
        "status": "online",
    }
]
