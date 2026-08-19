# r/algobetting — válasz-piszkozat (2026-08-19)

**Szál:** u/BigBalli — DNP a backtestben · https://old.reddit.com/r/algobetting/comments/1vrqoed/

## Mi történt

A poszter válaszolt a hozzászólásunkra, és **három dolgot tett**:

1. **Helyesbítette magát** — utánanézett a kódjában: nála a darabszám MÁR utazik
   az aránnyal (minden arány mellé kiírja az `n`-t, 3 meccs alatt nem is jelenít
   meg százalékot). Emlékezetből válaszolt korábban.
2. **Élesítette a pontot:** *„It travels because the call sites happen to pass
   it, which is exactly the arrangement that breaks the first time someone adds
   a third."* — a megoldás szerinte a TÍPUS, ami nem tud csupasz százalékot
   ábrázolni. Ezt a részt befejezetlennek nevezi.
3. **Felismerte a mi hibánk alakzatát:** *„Write time is a proxy for change time
   and it agrees right up until it doesn't."*

🔑 **A mérőszámunk teljesült, sőt túl:** nem csak kérdezett a saját adatáról —
**elment és megnézte a saját kódját**, és talált benne egy féligkész dolgot.

## 🔴 Amiben NEKÜNK kell helyesbíteni

Az ő appjáról tettem állítást (1-of-2 → 50%), amit **általános mintából**
következtettem, nem az ő kódjából. Nem állt meg. Ő nyilvánosan helyesbítette
magát; ugyanezt a mércét kell tartanunk.

## Amit hozzáteszünk

A TEGNAPI saját hibánk — friss, mért példa pontosan arra a hibafajtára, amit ő
megnevezett: a `stale-guard` négy rétege EGY NAPIG vak volt, mert a csomag a
repó venv-jében volt telepítve, az őr viszont rendszer-pythonnal fut. A tesztek
zöldek voltak, mert azok a venv-ben futottak — más példányt mértek, mint a
valóság. És ami tartóssá tette a javítást, az nem az import volt, hanem a
kapu-teszt, ami a PRODUKCIÓS értelmezőt indítja el.

Ez pontosan az ő „a hívási helyek véletlenül átadják" alakzata.

---

## ⚠️ ÁLLAPOT: MEGÍRVA, DE NEM MENT KI (2026-08-19)

Három próbálkozás az old.reddit felületen, mindhárom **`an error occurred
(status: 404)`** — friss oldalbetöltésből is. A fiókon ellenőrizve: **egyetlen
hozzászólás van**, a 19 órás eredeti; **semmi nem posztolódott duplán**.

Az eredeti hozzászólás ugyanezen a felületen, ugyanezzel a fiókkal 19 órája
gond nélkül kiment — tehát nem tiltás és nem a fiók.

## A szöveg (kiposztolásra vár)

Correction accepted — I inferred that from the general shape rather than from
your code, which is the move I was warning about. Fair.

The part you're calling not-done is the part I'd care about most. "It travels
because the call sites happen to pass it" is a guarantee living in a habit, and
habits are invisible until someone writes the third call site.

I got a fresh instance yesterday, on the freshness check itself. I'd wired four
new layers into my monitor two days earlier — tests green, done. They were blind
the entire time: the package was installed in the project's venv, the monitor
runs under system python. The tests passed because the tests ran in the venv,
so they were measuring a different copy than production was. A day of "OK" that
never once touched the thing it claimed to check.

It only surfaced because that layer reports BLIND rather than OK when it can't
measure. Had it defaulted to green I still wouldn't know.

What made the fix durable wasn't repairing the import. It was a test that spawns
the production interpreter and asserts the import worked *there* — so the check
now fails in the same environment that would break it. Same shape as your type
idea: stop relying on the right thing happening at the call site, make the wrong
thing unrepresentable.
