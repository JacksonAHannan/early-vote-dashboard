# A–G county precinct methodology review

Frozen snapshot: `2026-10-27T16:30:35.115243057+00:00`. All 94 assigned counties were individually checked against eight daily paired-coverage results, both native precinct universes, every retained source date/hash/unknown label and independent completed controls. No source gaps, zero votes or geographic aliases were invented.

## Accepted candidates

- **Collin:** the state Oct26file has13 votes. The official dated county workbook exposes29,932 ordinary Regular rows and133 Provisional rows, exactly reconciling the42-site inclusive check-in total 30,065. The collector excludes provisional rows and withholds the entire native 52 cell because one identity is blank. It retains29,725 ordinary votes in266 positive native precincts. All eight dated outputs are available; omitted precincts remain unknown.
- **Grayson:** official certified native presidential returns cover all 41 historical precincts, versus 13 previously classified. All 13 previous values agree. Both candidate totals (Trump 50,556, Harris 14,800), all other candidates and all 24 candidate/method totals conserve to the independently published official county summary. This restores classification without changing turnout or geography.

## Rejected source hypotheses

- **Gregg:** county pages and native 21 map confirm the native 1–21 district universe but do not define how each detailed SOS subdivision belongs to it. Some current labels are foreign or malformed, making generic numeric truncation unsafe. No turnout added.
- **Guadalupe:** the official May 13, 2025 order verifies 208 → 208 + 233 and 415 → 415 + 402, but supplies no 2024 four-digit subdivision-to-native relationship. Numerictruncation remains rejected.
- **Anderson, Bexar, Galveston and Grimes:** checked 07:51 and 16:30 editions do not reveal an earlier completed Oct 26 precinct source. Bexar current 18,364 is below the independent 43,839 control. Galveston moves 1 → 3 votes. These are underfilled publication observations, not completed same-day estimates.

## Verification

`python -m unittest discover -s sources/county-methodology/a-g -p "test_method_a_g*.py"` passes 21 contracts. Initial missing-collector and missing-native-reference verification were exercised red; CLI stdout contract was also red before implementation. Two live Collin collector runs pass, and their counts agree exactly with the independent earlier memory-only workbook probe. Every official Grayson candidate/method column and exact 41-ID partition reconciles; source PDF SHA256 editions are pinned. No raw voter bytes or identities were saved.

The full machine-readable ledger is `analysis/county-methodology/a-g/ledger.json`; it records every county’s diagnosis, all retained source URLs/hashes, individual date coverage, missing presidential reference IDs, disposition and concrete next action. `screen.py` regenerates the initial screening; `finalize.py` attaches the reviewed evidence and validates the 94-ID partition.

## Individual county screen

| County | Day1 paired | Day8 paired | Missing native presidential IDs | Disposition |
|---|---:|---:|---:|---|
|Anderson|22/22|0/22|0|real_source_gap|
|Andrews|4/4|4/4|0|healthy|
|Angelina|41/41|0/41|5|real_source_gap|
|Aransas|7/7|7/7|0|healthy|
|Archer|12/13|4/13|0|real_source_gap|
|Armstrong|6/8|2/8|0|real_source_gap|
|Atascosa|20/20|19/20|2|real_source_gap|
|Austin|10/10|10/10|3|real_source_gap|
|Bailey|4/4|3/4|1|real_source_gap|
|Bandera|10/10|0/10|0|real_source_gap|
|Bastrop|26/26|26/26|13|real_source_gap|
|Baylor|4/4|4/4|0|healthy|
|Bee|13/13|12/13|0|real_source_gap|
|Bell|71/72|71/72|0|real_source_gap|
|Bexar|670/806|606/806|67|real_source_gap|
|Blanco|5/5|5/5|4|real_source_gap|
|Borden|3/5|3/5|0|real_source_gap|
|Bosque|11/11|11/11|11|real_source_gap|
|Bowie|37/52|22/52|3|real_source_gap|
|Brazoria|82/84|79/84|12|real_source_gap|
|Brazos|74/77|68/77|27|real_source_gap|
|Brewster|8/8|5/8|0|real_source_gap|
|Briscoe|5/5|0/5|0|real_source_gap|
|Brooks|5/5|5/5|0|healthy|
|Brown|18/18|17/18|0|real_source_gap|
|Burleson|13/13|13/13|0|healthy|
|Burnet|21/21|19/21|0|real_source_gap|
|Caldwell|24/24|24/24|2|real_source_gap|
|Calhoun|11/11|11/11|9|real_source_gap|
|Callahan|8/8|8/8|0|healthy|
|Cameron|102/102|101/102|55|real_source_gap|
|Camp|4/4|4/4|0|healthy|
|Carson|8/8|0/8|0|real_source_gap|
|Cass|18/18|9/18|0|real_source_gap|
|Castro|8/8|5/8|0|real_source_gap|
|Chambers|18/19|18/19|2|real_source_gap|
|Cherokee|25/25|25/25|1|real_source_gap|
|Childress|4/4|4/4|0|healthy|
|Clay|16/16|8/16|0|real_source_gap|
|Cochran|4/5|4/5|0|real_source_gap|
|Coke|4/4|0/4|2|real_source_gap|
|Coleman|4/4|4/4|2|real_source_gap|
|Collin|256/273|0/273|0|proven_fix_candidate|
|Collingsworth|6/7|4/7|0|real_source_gap|
|Colorado|11/11|9/11|5|real_source_gap|
|Comal|41/41|41/41|20|real_source_gap|
|Comanche|14/14|8/14|0|real_source_gap|
|Concho|8/8|3/8|0|real_source_gap|
|Cooke|17/17|17/17|0|healthy|
|Coryell|16/16|13/16|8|real_source_gap|
|Cottle|4/4|3/4|0|real_source_gap|
|Crane|4/4|3/4|0|real_source_gap|
|Crockett|4/4|4/4|0|healthy|
|Crosby|4/4|4/4|0|healthy|
|Culberson|5/5|4/5|0|real_source_gap|
|Dallam|8/9|1/9|0|real_source_gap|
|Dallas|686/791|631/791|0|real_source_gap|
|Dawson|9/9|0/9|0|real_source_gap|
|Deaf Smith|4/4|4/4|0|healthy|
|Delta|7/7|5/7|0|real_source_gap|
|Denton|229/252|226/252|0|real_source_gap|
|DeWitt|10/10|10/10|0|healthy|
|Dickens|6/6|2/6|0|real_source_gap|
|Dimmit|7/7|5/7|0|real_source_gap|
|Donley|5/5|0/5|0|real_source_gap|
|Duval|8/9|7/9|0|real_source_gap|
|Eastland|9/9|8/9|0|real_source_gap|
|Ector|41/41|40/41|2|real_source_gap|
|Edwards|4/4|4/4|0|healthy|
|Ellis|60/61|60/61|1|real_source_gap|
|El Paso|207/236|201/236|43|real_source_gap|
|Erath|20/20|20/20|0|healthy|
|Falls|12/12|12/12|2|real_source_gap|
|Fannin|17/17|16/17|0|real_source_gap|
|Fayette|12/12|12/12|2|real_source_gap|
|Fisher|4/4|0/4|2|real_source_gap|
|Floyd|4/4|0/4|0|real_source_gap|
|Foard|4/4|2/4|0|real_source_gap|
|Fort Bend|194/201|186/201|0|real_source_gap|
|Franklin|8/8|8/8|2|real_source_gap|
|Freestone|13/13|1/13|11|real_source_gap|
|Frio|9/9|7/9|2|real_source_gap|
|Gaines|7/7|5/7|0|real_source_gap|
|Galveston|87/96|0/96|17|real_source_gap|
|Garza|6/6|0/6|0|real_source_gap|
|Gillespie|13/13|12/13|0|real_source_gap|
|Glasscock|4/4|3/4|0|real_source_gap|
|Goliad|9/9|7/9|0|real_source_gap|
|Gonzales|13/15|10/15|0|real_source_gap|
|Gray|7/7|6/7|0|real_source_gap|
|Grayson|42/42|41/42|28|proven_fix_candidate|
|Gregg|not admitted|not admitted|16|rejected|
|Grimes|13/13|0/13|0|real_source_gap|
|Guadalupe|not admitted|not admitted|12|rejected|
