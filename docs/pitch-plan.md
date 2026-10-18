# Pitch plan / План за питча (EN + BG)

For Emkata, who presents. Every number below comes from the repo docs or from runs on the **tuning seeds**; the held-out test seeds were run once (see [heldout-evaluation.md](heldout-evaluation.md)) and the numbers there are lower than the tuning numbers below, so say "in our tests", never "it is proven". / За Емката, който представя. Всички числа са от документите в репото или от пускания върху **tuning seeds**; тестовите seeds са пускани веднъж (виж [heldout-evaluation.md](heldout-evaluation.md)) и числата там са по-ниски от tuning числата по-долу, затова казвай „в нашите тестове“, не „доказано е“.

Timing assumes about 5 minutes; cut beats 5 and 6 first if you get less. / Времето е за около 5 минути; ако имаш по-малко, махни първо точки 5 и 6.

---

## 1. The one-sentence version / Едно изречение

**EN (pick one, vary between talks)**
- "We turn partial, noisy, delayed reports from cheap drones and ground sensors into one trusted picture of who is hostile, even when the enemy is jamming our radios."
- "Many weak sensors, a bad radio link, one clear answer: how many hostiles, where, and which ones are ours."
- "When the radios are jammed, our drones stop sending a clean picture. We rebuild it from what still gets through."

**BG (избери един, сменяй между изказванията)**
- „Превръщаме непълни, шумни и закъснели съобщения от евтини дронове и наземни сензори в една надеждна картина кой е враг, дори когато противникът заглушава връзката ни.“
- „Много слаби сензори, лоша радиовръзка, един ясен отговор: колко са враговете, къде са и кои са наши.“
- „Когато радиовръзката е заглушена, дроновете ни не получават чиста картина. Ние я възстановяваме от това, което все още стига.“

---

## 2. The story in six beats / Историята в шест стъпки

| # | Beat / Стъпка | Time / Време |
|---|---------------|--------------|
| 1 | Problem / Проблемът | 40 s |
| 2 | Our setup / Нашата постановка | 40 s |
| 3 | How it works / Как работи | 60 s |
| 4 | Live demo / Демо | 90 s |
| 5 | Results, honestly / Резултатите, честно | 50 s |
| 6 | What is next / Какво следва | 20 s |

### Beat 1 — The problem / Проблемът

**EN**
- Five of our drones and two ground sensors watch about one square kilometre. Two hostile drones fly through it and cross each other at close range.
- Electronic warfare means lost, late and jammed messages, clocks that drift, and positions we cannot fully trust.
- The commander needs three answers: how many hostiles, which track is which, and no friendly marked as a threat.

**BG**
- Пет наши дрона и два наземни сензора следят около един квадратен километър. Два вражески дрона прелитат и се разминават на много малко разстояние.
- Електронната борба означава загубени, закъснели и заглушени съобщения, часовници, които се разминават, и позиции, на които не можем напълно да вярваме.
- Командирът има нужда от три отговора: колко са враговете, кой трак кой е, и нито един наш дрон да не е маркиран като заплаха.

*Variation / Вариация:* start with a question. EN: "What do you do when you can see the enemy but your radios are being jammed?" BG: „Какво правиш, когато виждаш врага, но радиовръзката ти е заглушена?“

### Beat 2 — Our setup / Нашата постановка

**EN**
- Every sensor reports only what it really measures: a camera gives a direction, never a distance; radar gives range and speed; a radio receiver only hears transmitters.
- We simulate the whole chain: sensors, a lossy radio channel (loss, delay, jamming zones, bandwidth caps, node failures), the tracker, and a scorer that compares against the truth.
- Sensor numbers are our assumptions unless the catalog says "verified". Say this out loud; judges respect it.

**BG**
- Всеки сензор докладва само това, което наистина измерва: камерата дава посока, никога разстояние; радарът дава разстояние и скорост; радиоприемникът чува само предаватели.
- Симулираме цялата верига: сензори, радиоканал със загуби (загуба, закъснение, зони за заглушаване, ограничен капацитет, отпадане на възли), тракер и оценка спрямо истината.
- Числата за сензорите са наши допускания, освен ако в каталога не пише „verified“. Кажи го на глас, журито го уважава.

### Beat 3 — How it works / Как работи

Keep it as four steps; use the diagram in [project-summary.md](project-summary.md) section 3. / Дръж го на четири стъпки; ползвай диаграмата в [project-summary.bg.md](project-summary.bg.md).

| Step | EN | BG |
|------|----|----|
| Sense | Each drone and ground sensor makes noisy native readings. | Всеки дрон и наземен сензор прави шумни измервания. |
| Send | Readings and friendly position beacons go through a lossy channel. Only what arrives is used. | Измерванията и позиционните маяци на приятелите минават през канал със загуби. Ползва се само това, което пристигне. |
| Fuse | A Kalman tracker joins the readings into tracks with a position, a velocity and an uncertainty. | Калман тракер обединява измерванията в траекции с позиция, скорост и неопределеност. |
| Decide | A friend/foe estimator marks a track friendly when a beacon matches it. Behaviour alone never makes a track friendly. A suspicious track can send the closest drone for a second look. | Оценител приятел/враг маркира трака като наш, когато маяк съвпада с него. Поведението само не го прави наш. Подозрителен трак може да прати най-близкия дрон за втори поглед. |

**Two sentences worth memorising / Две изречения за наизустяване**
- EN: "A friendly is identified by its own position beacon, not by how it flies. Motion is a separate piece of evidence."
- BG: „Нашият дрон се разпознава по собствения му маяк, не по това как лети. Движението е отделно доказателство.“
- EN: "At the crossing, the radar's radial speed tells the two hostiles apart even when they pass within about 16 metres."
- BG: „При разминаването радиалната скорост от радара различава двата вражески дрона, дори когато минават на около 16 метра един от друг.“

### Beat 4 — Live demo / Демо

Open the viewer (`ui/viewer`, run `python serve.py`, port 8000). Script, about 90 seconds: / Отвори viewer-а (`ui/viewer`, `python serve.py`, порт 8000). Сценарий, около 90 секунди:

1. **`challenge` preset, clear.** Show the map: five drones on patrol, two ground sensors, two hostile tracks with uncertainty ellipses. / Покажи картата: пет дрона, два наземни сензора, два вражески трака с елипси на неопределеност.
2. **Press play through the crossing.** Point at the two track IDs: they stay the same after the pass. / Пусни през разминаването. Посочи двата ID-та: остават същите.
3. **Turn on loss and jamming** (the `jammed` preset). Say what the picture does: it gets thinner but does not lie. / Включи загуба и заглушаване (`jammed`). Кажи какво прави картината: оредява, но не лъже.
4. **`gnss_denied` preset** (our newest). Show that every node's position is wrong by up to 25 m, and that the estimator learns it from friendly beacons. / Покажи, че позицията на всеки възел е грешна до 25 м и че оценителят я научава от маяците на приятелите.

Rehearse once: the viewer only opens when `serve.py` is running, and the first load builds the scenarios. / Репетирай веднъж: viewer-ът се отваря само когато `serve.py` работи.

### Beat 5 — Results, honestly / Резултатите, честно

Say "tuning seeds, in our simulation". Do **not** say "proven". / Казвай „tuning seeds, в нашата симулация“. **Не** казвай „доказано“.

| What | Number | Say it like / Как да го кажеш |
|------|--------|-------------------------------|
| Hostile tracked | about 71 % of the time at 0 % loss on tuning seeds, 66 % on the held-out seeds | EN: "We see a hostile about seven times out of ten, and the limit is what the sensors can reach." BG: „Виждаме врага около седем пъти от десет; ограничението е какво достигат сензорите.“ |
| ID swaps at the crossing | 1.8 down to 0.3 per run on tuning seeds; about 1.0 per run (0.5 in the crossing window) on the held-out seeds | EN: "Using the radar's speed cut identity swaps from nearly two per run to about one in three." BG: „Скоростта от радара намали разменените ID-та от почти две на изпълнение до около едно на три.“ |
| Friendlies flagged | 0 of 5 up to 70 % loss, about 0.3 of 5 at 90 % on tuning seeds; 0.05 to 0.2 of 5 on the held-out seeds | EN: "Even with seven in ten messages lost, we flag none of our own drones." BG: „Дори с изгубени седем от десет съобщения не маркираме нито един наш дрон.“ |
| GNSS-denied nodes | position error about 25 m to 8 m; ID swaps about 7.5 to 0.5 per run (re-run on 6 tuning seeds, navigation off and on; the 8.8 to 3.2 first written here could not be reproduced) | EN: "When every node's position is wrong by up to 25 metres, learning the error from friendly beacons brings most of the accuracy back." BG: „Когато позицията на всеки възел е грешна до 25 метра, научаването на грешката от маяците на приятелите връща голямата част от точността.“ |

The GNSS number is from the viewer's simulation, on 6 tuning seeds, with an assumed error size and unbiased beacons. / Числото за GNSS е от симулацията във viewer-а, 6 tuning seeds, с допусната големина на грешката и без отклонение в маяците.

**What we tried and it did not help (a good story, it shows rigour) / Какво опитахме и не помогна (добра история, показва строгост):**
**Source needed / Трябва източник:** no script, result or commit in the repo records the placement test below (about three points); check it with Orlin before saying it. / в репото няма скрипт, резултат или комит за теста за разполагането по-долу (около три пункта); провери го с Орлин, преди да го кажеш.
- EN: "We tested whether better drone placement or a different mix of sensors would see hostiles more. It did not: the best layout moved coverage by about three points. The limit is that fixed patrols with narrow cameras cannot cover a square kilometre. The next gain has to come from moving drones to the threat."
- BG: „Тествахме дали по-добро разположение на дроновете или друга комбинация от сензори ще вижда повече врагове. Не: най-добрият вариант промени покритието с около три пункта. Ограничението е, че неподвижни патрули с тесни камери не покриват квадратен километър. Следващата крачка е дроновете да се местят към заплахата.“

### Beat 6 — What is next / Какво следва

**EN:** Agree acceptance thresholds (a proposal is in heldout-evaluation.md); label hostiles from evidence rather than "not friendly"; send drones toward the threat; show the Python pipeline live in the viewer (today a saved run can be replayed on cop.html).

**BG:** Да договорим праговете за приемане (предложение има в heldout-evaluation.md); да определяме враговете по доказателства, а не по „не е приятел“; да пращаме дронове към заплахата; да покажем Python конвейера на живо във viewer-а (днес записан пробег се възпроизвежда на cop.html).

---

## 3. Expected questions / Очаквани въпроси

| Question | EN answer | BG отговор |
|----------|-----------|------------|
| Is this proven? | "No. The components are built and tested; the challenge result is measured on tuning seeds only. The held-out run is the next step." | „Не. Компонентите са изградени и тествани; резултатът е измерен само на tuning seeds. Следва тест върху отделените seeds.“ |
| Why only 71 %? | "Measured on our tuning seeds: about 1 % of the time nothing sees it, about 16 % only a radio receiver hears it (a direction with 12 degrees of noise), and about 9 % only one camera or microphone has a bearing. A bearing alone cannot start a track." | „Измерено на tuning seeds: около 1 % от времето нищо не го вижда, около 16 % го чува само радиоприемник (посока с 12 градуса шум), а около 9 % само една камера или микрофон има посока. Една посока сама не може да започне трак.“ |
| Could a hostile be called friendly? | "Not by behaviour. A friendly needs a matching beacon. In our tests a hostile was never called friendly." | „Не по поведение. Нашият дрон има нужда от съвпадащ маяк. В тестовете враг никога не е наречен приятел.“ |
| Do you use ground truth in the tracker? | "No. Only the scorer reads the truth file." | „Не. Само оценката чете файла с истината.“ |
| Why a classical tracker, not AI? | "It is explainable, predictable, and works without training data; AI is optional for prediction only." | „Обясним е, предвидим е и работи без данни за обучение; ИИ е по избор, само за прогноза.“ |
| What if the link is 90 % lost? | "On the held-out seeds hostiles are tracked about a third of the time (0.35), and we flag 0.2 of 5 friendlies on average. It degrades; it does not collapse." | „На скритите seeds враговете се следят около една трета от времето (0,35) и маркираме средно 0,2 от 5 приятели. Влошава се, но не се срива.“ |
| Are the sensor numbers real? | "They are assumptions unless the catalog says verified. We list which." | „Допускания са, освен ако в каталога не пише verified. Знаем кои са.“ |
| Is it distributed? | "Partly. Each node can run its own tracker and share compact tracks with one merger; that mode tracks hostiles about seven points worse than the central one and has no failover yet." | „Частично. Всеки възел може да върти собствен тракер и да споделя компактни траектории с един обединител; режимът следи враговете с около седем пункта по-зле и още няма резервен обединител.“ |

---

## 4. Do not say / Не казвай

- "Solved", "proven", "guaranteed". / „Решено“, „доказано“, „гарантирано“.
- A held-out number without saying it is held-out and lower than the tuning numbers (see heldout-evaluation.md). / Число от тестовите seeds, без да кажеш, че е от тестовите и че е по-ниско от tuning числата.
- That the main viewer shows the Python tracker live: it does not, it runs its own simulation; the COP replay page (cop.html) can replay a saved Python run. / Че основният viewer показва Python тракера на живо: не го показва, има собствена симулация; страницата cop.html може да възпроизведе записан Python пробег.
- That hostiles are detected "from evidence": today every track that is not a confirmed friendly counts as hostile. / Че враговете се определят „по доказателства“: днес всеки трак, който не е потвърден приятел, се брои за враг.

## 5. Phrases for variety / Фрази за разнообразие

**Transitions / Преходи**
- EN: "So that is the problem. Here is what we built." / "Let me show you instead of telling you." / "Now the honest part."
- BG: „Това е проблемът. Ето какво построихме.“ / „Нека да ви покажа, вместо да обяснявам.“ / „Сега честната част.“

**Closers / Завършек**
- EN: "Cheap sensors, bad radios, one clear picture." / "We would rather tell you what we have not proven than claim what we cannot show."
- BG: „Евтини сензори, лоша връзка, една ясна картина.“ / „По-добре да ви кажем какво не сме доказали, отколкото да твърдим нещо, което не можем да покажем.“

**Analogy for a non-technical audience / Аналогия за нетехническа публика**
- EN: "Think of five people in a dark field, each seeing only a direction, shouting over a bad phone line. We turn the shouts into a map."
- BG: „Представете си пет човека в тъмно поле, всеки вижда само посока и вика по лоша телефонна линия. Ние превръщаме виковете в карта.“

## 6. Source documents / Източници

[README.md](../README.md), [project-summary.md](project-summary.md), [project-summary.bg.md](project-summary.bg.md), [challenge-audit.md](challenge-audit.md), [tracker.md](../tracker/tracker.md). / Същите, за проверка на числата.
