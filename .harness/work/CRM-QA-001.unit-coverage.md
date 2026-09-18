# CRM-QA-001 unit coverage — current 897-test run

- JUnit: `897 passed`, `0 failed`, `0 skipped`.
- Line coverage: `13,965 / 14,949 = 93.42%` (manual line gate, above 91%).
- Branch coverage: `2,345 / 3,120 = 75.16%`.
- Coverage.py combined line+branch display: `90.27%`.

| Name                                    |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|---------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| config\\\_\_init\_\_.py                 |        0 |        0 |        0 |        0 |    100% |           |
| config\\access.py                       |       35 |        0 |        4 |        0 |    100% |           |
| config\\modules.py                      |        1 |        0 |        0 |        0 |    100% |           |
| config\\settings.py                     |       73 |        0 |        8 |        0 |    100% |           |
| core\\\_\_init\_\_.py                   |        0 |        0 |        0 |        0 |    100% |           |
| core\\db\\\_\_init\_\_.py               |        0 |        0 |        0 |        0 |    100% |           |
| core\\db\\base.py                       |        6 |        0 |        0 |        0 |    100% |           |
| core\\db\\repository.py                 |       24 |        0 |        2 |        0 |    100% |           |
| core\\domain\\\_\_init\_\_.py           |        2 |        0 |        0 |        0 |    100% |           |
| core\\domain\\models.py                 |      138 |        0 |        0 |        0 |    100% |           |
| core\\domain\\reference.py              |      111 |        0 |        0 |        0 |    100% |           |
| core\\reference\\\_\_init\_\_.py        |        0 |        0 |        0 |        0 |    100% |           |
| core\\reference\\account\_plan.py       |        6 |        0 |        0 |        0 |    100% |           |
| core\\runtime\\\_\_init\_\_.py          |        0 |        0 |        0 |        0 |    100% |           |
| core\\runtime\\access.py                |       34 |        1 |       12 |        1 |     96% |       110 |
| core\\runtime\\app.py                   |       84 |       10 |       14 |        0 |     90% |88, 107-115 |
| core\\runtime\\approval\_routes.py      |       33 |       16 |        8 |        0 |     41% |25-30, 40-47, 58, 69 |
| core\\runtime\\contract.py              |       49 |        0 |        0 |        0 |    100% |           |
| core\\runtime\\core.py                  |       79 |        1 |        2 |        1 |     98% |81-\>83, 126 |
| core\\runtime\\deps.py                  |       14 |        7 |        2 |        0 |     44% | 14, 19-24 |
| core\\runtime\\funnel.py                |       42 |        0 |        4 |        0 |    100% |           |
| core\\runtime\\identity\_routes.py      |      278 |       12 |       58 |        0 |     96% |694-698, 704-709, 729-731 |
| core\\runtime\\loader.py                |       23 |        2 |        6 |        2 |     86% |    25, 30 |
| core\\runtime\\reference\_registry.py   |       13 |        0 |        2 |        0 |    100% |           |
| core\\runtime\\reference\_routes.py     |      193 |       17 |       52 |       10 |     89% |67, 132, 157-\>159, 176-179, 233, 258, 273-\>243, 287-289, 314-\>316, 323, 332, 346-\>354, 360-361, 370-372 |
| core\\runtime\\system\_routes.py        |      278 |        1 |       70 |        8 |     97% |329, 470-\>477, 493-\>499, 495-\>493, 523-\>535, 635-\>651, 642-\>645, 665-\>673 |
| core\\runtime\\telegram\_routes.py      |       61 |        0 |       26 |        1 |     99% |   92-\>94 |
| core\\services\\\_\_init\_\_.py         |       46 |        0 |        0 |        0 |    100% |           |
| core\\services\\approvals.py            |       59 |        0 |        4 |        0 |    100% |           |
| core\\services\\auth.py                 |       81 |        1 |       20 |        1 |     98% |        90 |
| core\\services\\bank.py                 |        4 |        0 |        0 |        0 |    100% |           |
| core\\services\\config.py               |        3 |        0 |        0 |        0 |    100% |           |
| core\\services\\db.py                   |       42 |       21 |       10 |        0 |     48% |49-71, 75-77 |
| core\\services\\eventbus.py             |       45 |       15 |       10 |        0 |     62% |41-42, 56, 80-103 |
| core\\services\\gsheets.py              |       30 |        0 |        4 |        0 |    100% |           |
| core\\services\\incident\_alerts.py     |       60 |        2 |       10 |        3 |     93% |41-\>43, 47, 49 |
| core\\services\\keycloak\_admin.py      |      146 |        9 |       32 |        6 |     92% |104-105, 184, 192-193, 221, 228-229, 321 |
| core\\services\\landed\_cost.py         |       64 |        1 |       16 |        1 |     98% |       113 |
| core\\services\\litellm.py              |       15 |        0 |        4 |        0 |    100% |           |
| core\\services\\mdm.py                  |      153 |        3 |       58 |       11 |     93% |167-\>169, 172-\>178, 179-\>181, 181-\>183, 183-\>185, 211-\>213, 249-\>251, 257, 300, 302, 337-\>339 |
| core\\services\\onec.py                 |        4 |        0 |        0 |        0 |    100% |           |
| core\\services\\price\_cost.py          |       15 |        0 |        0 |        0 |    100% |           |
| core\\services\\price\_cost\_demo.py    |       20 |        0 |        4 |        0 |    100% |           |
| core\\services\\reference\_import.py    |       72 |        1 |       26 |        1 |     98% |        99 |
| core\\services\\reference\_quality.py   |      119 |        2 |       36 |        3 |     97% |101, 160, 259-\>257 |
| core\\services\\reference\_query.py     |      117 |        2 |       58 |        4 |     97% |125, 176-\>178, 181, 261-\>263 |
| core\\services\\registry.py             |        3 |        0 |        0 |        0 |    100% |           |
| core\\services\\scd2.py                 |       21 |        0 |        4 |        1 |     96% |   45-\>49 |
| core\\services\\sku\_history.py         |       15 |        0 |        2 |        0 |    100% |           |
| core\\services\\sku\_master.py          |       40 |        2 |       10 |        2 |     92% |    31, 59 |
| core\\services\\stock.py                |        4 |        0 |        0 |        0 |    100% |           |
| core\\services\\survivorship.py         |       45 |        0 |       14 |        0 |    100% |           |
| core\\services\\sync\_outbound.py       |       54 |        1 |       16 |        1 |     97% |        83 |
| core\\services\\telephony.py            |        3 |        0 |        0 |        0 |    100% |           |
| core\\services\\temporal.py             |       11 |        0 |        0 |        0 |    100% |           |
| core\\services\\tnved.py                |       54 |        2 |       22 |        4 |     92% |37-\>42, 39-\>42, 75, 116 |
| core\\services\\touch\_history.py       |        6 |        1 |        0 |        0 |     83% |        29 |
| modules\\\_\_init\_\_.py                |        0 |        0 |        0 |        0 |    100% |           |
| modules\\finance\\\_\_init\_\_.py       |        0 |        0 |        0 |        0 |    100% |           |
| modules\\finance\\aging.py              |       44 |        0 |       18 |        0 |    100% |           |
| modules\\finance\\allocation.py         |       25 |        0 |        6 |        2 |     94% |62-\>72, 70-\>72 |
| modules\\finance\\balance\_sheet.py     |       49 |        0 |        8 |        4 |     93% |91-\>102, 94-\>102, 103-\>112, 106-\>112 |
| modules\\finance\\bank\_ingest.py       |      102 |        2 |       38 |        4 |     96% |70-\>72, 107, 110, 113-\>116 |
| modules\\finance\\cashflow.py           |       72 |        4 |       26 |        5 |     91% |68-\>70, 100, 118-\>111, 126, 128-129, 131-\>122 |
| modules\\finance\\cashflow\_dds.py      |       41 |        2 |       16 |        6 |     86% |56-\>58, 58-\>61, 72-\>74, 74-\>77, 87-\>95, 90-\>95, 92-93 |
| modules\\finance\\cost\_center.py       |       34 |        0 |       14 |        2 |     96% |45-\>47, 47-\>49 |
| modules\\finance\\events.py             |      160 |        7 |       66 |        6 |     94% |125-126, 154-\>156, 156-\>158, 164-165, 263-\>282, 273-278, 283, 289-\>295 |
| modules\\finance\\fx.py                 |       15 |        0 |        4 |        0 |    100% |           |
| modules\\finance\\margin.py             |       84 |        0 |       22 |        2 |     98% |69-\>55, 167-\>174 |
| modules\\finance\\models.py             |       60 |        0 |        0 |        0 |    100% |           |
| modules\\finance\\module.py             |       27 |        0 |        0 |        0 |    100% |           |
| modules\\finance\\pnl.py                |       42 |        0 |        8 |        3 |     94% |70-\>72, 72-\>75, 77-\>76 |
| modules\\finance\\reconcile.py          |       56 |        0 |       18 |        0 |    100% |           |
| modules\\finance\\routes.py             |      245 |        9 |       66 |       11 |     94% |66-\>68, 120-123, 335-\>337, 450-\>452, 472, 515, 517-\>522, 544, 586-\>588, 601, 606, 609 |
| modules\\finance\\schemas.py            |       93 |        0 |        0 |        0 |    100% |           |
| modules\\finance\\summary.py            |       33 |        0 |        2 |        0 |    100% |           |
| modules\\hr\\\_\_init\_\_.py            |        0 |        0 |        0 |        0 |    100% |           |
| modules\\hr\\models.py                  |       50 |        0 |        0 |        0 |    100% |           |
| modules\\hr\\module.py                  |       13 |        0 |        0 |        0 |    100% |           |
| modules\\hr\\routes.py                  |      125 |        0 |       24 |        6 |     96% |89-\>91, 122-\>124, 124-\>126, 126-\>128, 249-\>251, 251-\>253 |
| modules\\hr\\schemas.py                 |       74 |        0 |        0 |        0 |    100% |           |
| modules\\hr\\stages.py                  |        1 |        0 |        0 |        0 |    100% |           |
| modules\\integrations\\\_\_init\_\_.py  |        0 |        0 |        0 |        0 |    100% |           |
| modules\\integrations\\alfa.py          |       13 |        0 |        0 |        0 |    100% |           |
| modules\\integrations\\client.py        |      106 |       12 |       28 |        1 |     90% |70, 81-82, 86-91, 210, 213, 216 |
| modules\\integrations\\models.py        |       32 |        0 |        0 |        0 |    100% |           |
| modules\\integrations\\module.py        |       29 |        2 |        2 |        1 |     90% |     37-39 |
| modules\\integrations\\price\_cost.py   |       33 |        3 |       16 |        1 |     84% |     50-52 |
| modules\\integrations\\registry.py      |       28 |        0 |        6 |        0 |    100% |           |
| modules\\integrations\\routes.py        |      131 |        3 |       34 |        3 |     96% |36-\>48, 70, 110-\>101, 237, 269 |
| modules\\integrations\\schemas.py       |       19 |        0 |        0 |        0 |    100% |           |
| modules\\integrations\\service.py       |       37 |        0 |        6 |        2 |     95% |41-\>44, 46-\>50 |
| modules\\integrations\\stock.py         |       62 |        2 |       24 |        2 |     95% |    40, 56 |
| modules\\integrations\\sync\_tick.py    |        7 |        0 |        2 |        0 |    100% |           |
| modules\\integrations\\telephony.py     |       86 |        0 |       32 |        0 |    100% |           |
| modules\\knowledge\\\_\_init\_\_.py     |        0 |        0 |        0 |        0 |    100% |           |
| modules\\knowledge\\models.py           |       29 |        0 |        0 |        0 |    100% |           |
| modules\\knowledge\\module.py           |       13 |        0 |        0 |        0 |    100% |           |
| modules\\knowledge\\routes.py           |       81 |        4 |       22 |        7 |     89% |55-56, 65-\>67, 79, 98-\>100, 100-\>102, 138, 141-\>145, 142-\>144 |
| modules\\knowledge\\schemas.py          |       43 |        0 |        0 |        0 |    100% |           |
| modules\\knowledge\\stages.py           |        1 |        0 |        0 |        0 |    100% |           |
| modules\\leads\\\_\_init\_\_.py         |        0 |        0 |        0 |        0 |    100% |           |
| modules\\leads\\ai.py                   |        7 |        0 |        0 |        0 |    100% |           |
| modules\\leads\\events.py               |      114 |       11 |       36 |       11 |     85% |69, 72, 87-\>95, 94, 116-121, 136-\>139, 159, 197-\>199, 221-\>224, 248, 256-\>exit |
| modules\\leads\\leads.py                |      171 |       47 |       72 |        1 |     71% |224, 239-253, 275-280, 295-322, 333-334, 370-388, 398-415 |
| modules\\leads\\models.py               |       75 |        0 |        0 |        0 |    100% |           |
| modules\\leads\\module.py               |       27 |        1 |        2 |        0 |     97% |        44 |
| modules\\leads\\permissions.py          |        4 |        0 |        0 |        0 |    100% |           |
| modules\\leads\\planning.py             |       60 |        3 |       16 |        3 |     92% |124, 126, 128 |
| modules\\leads\\routes.py               |      418 |       88 |       94 |       29 |     75% |97-\>110, 132-133, 158-160, 192-204, 285-302, 331, 349-\>351, 368-\>370, 371, 382-\>385, 539-554, 566-590, 640, 660, 687, 691, 695-\>699, 726, 768, 770, 772, 809-839, 895, 897, 899, 957, 961-962, 998, 1000, 1039, 1048, 1054, 1073-1078, 1090, 1093-1094, 1121, 1124-1127 |
| modules\\leads\\schemas.py              |      184 |        4 |        4 |        1 |     96% | 46, 52-54 |
| modules\\leads\\storage.py              |       58 |        2 |       14 |        2 |     94% |    55, 81 |
| modules\\legal\\\_\_init\_\_.py         |        0 |        0 |        0 |        0 |    100% |           |
| modules\\legal\\models.py               |       20 |        0 |        0 |        0 |    100% |           |
| modules\\legal\\module.py               |       13 |        0 |        0 |        0 |    100% |           |
| modules\\legal\\routes.py               |       48 |        2 |        6 |        1 |     94% |58-59, 70-\>72 |
| modules\\legal\\schemas.py              |       26 |        0 |        0 |        0 |    100% |           |
| modules\\legal\\stages.py               |        1 |        0 |        0 |        0 |    100% |           |
| modules\\logistics\\\_\_init\_\_.py     |        0 |        0 |        0 |        0 |    100% |           |
| modules\\logistics\\analytics.py        |       41 |        0 |       12 |        1 |     98% |   86-\>85 |
| modules\\logistics\\events.py           |       70 |        4 |       28 |        7 |     89% |52, 70-\>72, 88, 136, 149, 160-\>169, 164-\>169 |
| modules\\logistics\\fleet.py            |       23 |        0 |       14 |        0 |    100% |           |
| modules\\logistics\\models.py           |      192 |        0 |        0 |        0 |    100% |           |
| modules\\logistics\\module.py           |       18 |        0 |        0 |        0 |    100% |           |
| modules\\logistics\\notify.py           |       50 |        0 |       16 |        2 |     97% |80-\>82, 82-\>84 |
| modules\\logistics\\pricing.py          |       63 |        0 |       16 |        0 |    100% |           |
| modules\\logistics\\routes.py           |      615 |       83 |      166 |       30 |     81% |159, 165-166, 178-\>180, 197-\>220, 212-\>220, 239-279, 294-310, 317, 325-326, 337-342, 359-\>361, 374-378, 391, 394-\>396, 396-\>404, 404-\>424, 414-\>424, 456, 585-\>583, 598-601, 693-703, 759-\>761, 783-790, 874-\>873, 881-\>880, 1060-\>1062, 1107, 1139, 1154-\>1157, 1165-\>1167, 1209, 1226, 1236, 1262, 1271-\>1273, 1295, 1333, 1335, 1340, 1352-\>1355, 1387, 1436, 1445-\>1434 |
| modules\\logistics\\schemas.py          |      434 |        0 |        0 |        0 |    100% |           |
| modules\\logistics\\seeds.py            |       24 |        0 |        4 |        0 |    100% |           |
| modules\\logistics\\stages.py           |        3 |        0 |        0 |        0 |    100% |           |
| modules\\marketing\\\_\_init\_\_.py     |        0 |        0 |        0 |        0 |    100% |           |
| modules\\marketing\\models.py           |       66 |        0 |        0 |        0 |    100% |           |
| modules\\marketing\\module.py           |       16 |        0 |        0 |        0 |    100% |           |
| modules\\marketing\\routes.py           |       33 |        0 |        2 |        0 |    100% |           |
| modules\\marketing\\schemas.py          |       33 |        0 |        0 |        0 |    100% |           |
| modules\\marketing\\seo\_events.py      |       23 |        0 |       10 |        0 |    100% |           |
| modules\\marketing\\seo\_routes.py      |       74 |        0 |       14 |        1 |     99% | 102-\>101 |
| modules\\marketing\\seo\_schemas.py     |       70 |        0 |        0 |        0 |    100% |           |
| modules\\marketing\\seo\_service.py     |       75 |        2 |       30 |        5 |     91% |61-62, 118-\>127, 129-\>131, 148-\>152, 150-\>152 |
| modules\\marketing\\seo\_webhook.py     |      130 |       10 |       46 |       10 |     88% |66, 74-82, 93, 102-\>116, 136-\>139, 209, 238-240, 248, 261-\>263, 278 |
| modules\\office\\\_\_init\_\_.py        |        0 |        0 |        0 |        0 |    100% |           |
| modules\\office\\carriers.py            |        5 |        0 |        0 |        0 |    100% |           |
| modules\\office\\events.py              |      144 |        1 |       42 |        3 |     98% |242, 281-\>284, 376-\>378 |
| modules\\office\\models.py              |       59 |        0 |        0 |        0 |    100% |           |
| modules\\office\\module.py              |       21 |        0 |        0 |        0 |    100% |           |
| modules\\office\\routes.py              |      154 |       21 |       44 |        8 |     81% |42-43, 60, 66-67, 73, 88-\>90, 116-\>120, 145, 160-\>162, 199-204, 219-\>222, 244, 263-268, 283-\>286, 308 |
| modules\\office\\schemas.py             |      115 |        0 |        0 |        0 |    100% |           |
| modules\\office\\stages.py              |        1 |        0 |        0 |        0 |    100% |           |
| modules\\procurement\\\_\_init\_\_.py   |        0 |        0 |        0 |        0 |    100% |           |
| modules\\procurement\\cost\_estimate.py |       51 |        0 |        2 |        0 |    100% |           |
| modules\\procurement\\events.py         |       84 |        8 |       38 |        9 |     86% |24, 53, 85, 108, 128-\>132, 147, 168, 173, 176 |
| modules\\procurement\\landed\_cost.py   |       20 |        0 |        6 |        0 |    100% |           |
| modules\\procurement\\models.py         |      157 |        0 |        0 |        0 |    100% |           |
| modules\\procurement\\module.py         |       20 |        0 |        0 |        0 |    100% |           |
| modules\\procurement\\plan.py           |       40 |        0 |        8 |        0 |    100% |           |
| modules\\procurement\\routes.py         |      542 |       86 |      166 |       31 |     81% |111, 186, 194-196, 204-213, 224-241, 263-290, 299-310, 320-\>330, 408, 413, 432, 547-550, 557-564, 573, 595-\>597, 640-\>659, 653-\>659, 681, 711, 727-\>731, 729-\>731, 744, 797-821, 850, 859, 874, 944-950, 971-974, 984, 1012, 1014, 1018, 1040-\>1042, 1074, 1111-\>1117, 1153-1154, 1184, 1187-\>1189, 1190-\>1189, 1216, 1250, 1281-1284, 1300, 1308, 1328 |
| modules\\procurement\\schemas.py        |      257 |        0 |        0 |        0 |    100% |           |
| modules\\procurement\\stages.py         |        1 |        0 |        0 |        0 |    100% |           |
| modules\\production\\\_\_init\_\_.py    |        0 |        0 |        0 |        0 |    100% |           |
| modules\\production\\events.py          |       21 |        3 |        8 |        3 |     79% |32, 36, 69 |
| modules\\production\\models.py          |       80 |        0 |        0 |        0 |    100% |           |
| modules\\production\\module.py          |       15 |        0 |        0 |        0 |    100% |           |
| modules\\production\\routes.py          |      351 |        2 |       82 |       12 |     97% |126-\>138, 136-\>138, 140-\>142, 159-\>173, 190-\>192, 214-\>216, 294, 343-\>354, 519-\>521, 533-\>535, 576-\>575, 585 |
| modules\\production\\schemas.py         |      186 |        0 |        0 |        0 |    100% |           |
| modules\\production\\stages.py          |        1 |        0 |        0 |        0 |    100% |           |
| modules\\sales\\\_\_init\_\_.py         |        0 |        0 |        0 |        0 |    100% |           |
| modules\\sales\\\_money\_words.py       |       58 |        0 |       26 |        1 |     99% |   45-\>47 |
| modules\\sales\\ai.py                   |       37 |        0 |        4 |        0 |    100% |           |
| modules\\sales\\calls.py                |      150 |        7 |       72 |       11 |     92% |48-\>exit, 50-\>exit, 147-\>151, 254, 255-\>257, 265, 267, 277, 279, 301, 303 |
| modules\\sales\\events.py               |      142 |       29 |       58 |       14 |     76% |13, 28, 70-\>exit, 72-\>74, 94-\>exit, 109, 131, 141-\>147, 161-184, 241, 254, 259, 267, 294, 298, 309-310 |
| modules\\sales\\kpi\_facts.py           |       35 |        0 |        0 |        0 |    100% |           |
| modules\\sales\\models.py               |      212 |        0 |        0 |        0 |    100% |           |
| modules\\sales\\module.py               |       46 |        1 |        4 |        0 |     98% |        83 |
| modules\\sales\\permissions.py          |        4 |        0 |        0 |        0 |    100% |           |
| modules\\sales\\repository.py           |       17 |        2 |        0 |        0 |     88% |     17-18 |
| modules\\sales\\reserve.py              |       25 |        0 |        8 |        2 |     94% |38-\>40, 64-\>34 |
| modules\\sales\\routes.py               |     1585 |      321 |      556 |      149 |     74% |200, 387, 400-404, 421, 464, 473-\>481, 484-\>486, 486-\>483, 510-\>514, 536-\>534, 576-577, 584, 588-\>601, 622-\>616, 690-692, 694-\>693, 714-715, 717-\>719, 770, 775, 793-805, 827-859, 889, 905-908, 911-\>925, 918-\>925, 921-\>920, 931, 937, 946-948, 970-972, 992-\>994, 1015-1035, 1043, 1049-\>1058, 1060-\>1076, 1120-\>1126, 1172, 1180-1186, 1202, 1210-\>1224, 1219-\>1224, 1225-1230, 1231-\>1233, 1236-\>1238, 1279-\>1291, 1292-\>1296, 1297-\>1300, 1312-1315, 1321-1324, 1369-1392, 1412, 1422-1445, 1479, 1495-\>1490, 1504, 1506-\>1509, 1511, 1513, 1553, 1558-\>1564, 1569-1577, 1581, 1584-1587, 1633, 1641, 1652-\>1669, 1663-1664, 1670-\>1682, 1679-\>1677, 1693, 1695, 1699, 1708-1711, 1755-\>1754, 1782-1797, 1821-\>1823, 1842-\>1837, 1848-\>1860, 1863-\>1867, 1875-\>1877, 1880-\>1884, 1905-\>1902, 1918-1920, 1940-\>1947, 1963-\>1977, 1978-\>1987, 2032-2039, 2067-\>2071, 2096, 2098, 2126, 2128, 2175, 2177, 2230, 2234, 2242, 2276, 2280, 2330, 2360, 2365-\>2372, 2383-2392, 2405, 2427-\>2432, 2438-2445, 2458, 2471, 2514, 2526, 2539, 2556, 2559-\>2561, 2589-2591, 2625, 2631-2642, 2663-\>2665, 2673, 2708, 2711-\>2732, 2715-\>2732, 2754, 2756, 2758, 2767-\>2770, 2771-2772, 2867, 2873-2874, 2891, 2895, 2896-\>2898, 2903-2916, 2970-2996, 3171-\>3173, 3179, 3195-3202, 3222, 3245, 3270-3273, 3279-3296, 3309-\>3311, 3312, 3348, 3357, 3396, 3399, 3426, 3429, 3483, 3577, 3610, 3613, 3658, 3665-\>3681, 3709, 3711, 3716-\>3732, 3763-3772, 3790, 3792, 3798-3799, 3814, 3830, 3848, 3871, 3875, 3880-3881, 3892-3894, 3922, 3942-3943, 3947-3948 |
| modules\\sales\\schemas.py              |      525 |        1 |        2 |        1 |     99% |       920 |
| modules\\sales\\stages.py               |       14 |        0 |        0 |        0 |    100% |           |
| modules\\sales\\telegram.py             |        5 |        1 |        0 |        0 |     80% |         9 |
| modules\\sales\\touch\_history.py       |       57 |        0 |       12 |        0 |    100% |           |
| modules\\sales\\workflows.py            |        5 |        0 |        0 |        0 |    100% |           |
| modules\\service\\\_\_init\_\_.py       |        0 |        0 |        0 |        0 |    100% |           |
| modules\\service\\models.py             |       25 |        0 |        0 |        0 |    100% |           |
| modules\\service\\module.py             |       29 |        0 |        6 |        0 |    100% |           |
| modules\\service\\routes.py             |       47 |        1 |        8 |        2 |     95% |41-\>43, 76 |
| modules\\service\\schemas.py            |       33 |        0 |        0 |        0 |    100% |           |
| modules\\wms\\\_\_init\_\_.py           |        0 |        0 |        0 |        0 |    100% |           |
| modules\\wms\\events.py                 |       35 |        0 |       12 |        1 |     98% |   78-\>80 |
| modules\\wms\\models.py                 |      130 |        0 |        0 |        0 |    100% |           |
| modules\\wms\\module.py                 |       22 |        0 |        2 |        0 |    100% |           |
| modules\\wms\\permissions.py            |        4 |        0 |        0 |        0 |    100% |           |
| modules\\wms\\routes.py                 |      632 |       59 |      202 |       47 |     85% |92-100, 271-\>273, 273-\>275, 303-\>305, 305-\>307, 343-\>345, 345-\>347, 446-447, 489-490, 501, 505, 522-\>498, 614-\>616, 717, 775-778, 791-\>793, 805-808, 827, 874-\>876, 876-\>878, 905, 908, 959-964, 974-977, 1024, 1026, 1038, 1043, 1044-\>1046, 1066, 1068-1070, 1078-\>1076, 1123-\>1125, 1125-\>1127, 1128, 1157, 1159, 1161, 1163, 1165, 1167, 1169, 1170-\>1189, 1181-\>1187, 1221-\>1223, 1256, 1264, 1267, 1304-\>1306, 1373-\>1381, 1375-\>1374, 1383, 1462, 1513 |
| modules\\wms\\schemas.py                |      326 |        0 |        0 |        0 |    100% |           |
| modules\\wms\\stages.py                 |        1 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                               | **14928** |  **980** | **3108** |  **527** | **90%** |           |
