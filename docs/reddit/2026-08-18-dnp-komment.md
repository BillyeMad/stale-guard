# r/algobetting — hozzászólás (2026-08-18)

**Szál:** u/BigBalli — *„When you backtest a player prop, does a DNP count as a
loss or does it not count at all?"*
https://www.reddit.com/r/algobetting/comments/1vrqoed/

## 🔴 A piszkozat ÁTÍRVA posztolás előtt

Az első változat három pontot hozott. A szál megnyitása után kiderült, hogy
**kettő már el van mondva**:

| pont | ki mondta már |
|---|---|
| az elérhetőség külön sorozat legyen | SimTheGame · és egy másik hozzászóló |
| az üres ablak null legyen, ne 0% | SimTheGame · Icy_Cap_6898 |
| **a részleges ablaknál a darabszám utazzon az aránnyal** | **senki** |
| **az ellenőrizetlen szám alsó korlát** | **senki** |

Változatlanul kitéve nagyrészt ismétlés lett volna — pont az ellenkezője annak,
amiért írjuk. Ezért a végleges szöveg **elismeri, ami már elhangzott**, és csak
azzal foglalkozik, ami hiányzik.

🔑 **Tanulság a módszerre:** a hozzászólást a szál MEGNYITÁSA UTÁN kell
véglegesíteni, nem a poszt szövegéből. A lista tetején látszó „3 hozzászólás"
nem mondja meg, hogy azok pont a te pontjaidat viszik-e el.

---

## ✅ KIPOSZTOLVA — 2026-08-18 21:5x, BillyeMad85

https://old.reddit.com/r/algobetting/comments/1vrqoed/

## A kiposztolt szöveg

Two of these are already covered above — availability as its own series, and
null rather than 0% — so I'll add the one I haven't seen mentioned.

When the window is partial, the count has to travel with the rate. 1-of-2 and
5-of-10 both render as 50%, and once that number leaves the function nothing
downstream can tell them apart. Null for the empty case fixes the 0-of-0 lie;
it doesn't fix the 1-of-2 one.

Related, from a different domain — odds snapshots rather than props. I had a
freshness check that reported "fresh" for 47 hours straight while the data
hadn't changed by a single byte: 2,413 snapshots, 308 unique contents. It was
measuring when the file was written, not when it changed. Green the whole time,
and I was computing closing line value against prices that were two days old.

What I took from it: an unverified number is a lower bound and should say so.
Mine now reports "changed at least 3h ago" until it has actually observed a
change, because on the first observation it genuinely cannot know whether the
thing has been frozen for a week. Reporting OK there would be a guess wearing
the costume of a measurement — same family as rendering 0-of-0 as 0%.
