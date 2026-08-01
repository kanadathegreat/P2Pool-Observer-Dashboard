"""
help_content.py
-----------------
The real help text. Kept separate from help_window.py so editing
wording later never means touching any code -- just this string.
"""

HELP_TEXT = """
<h2>What is P2Pool?</h2>
<p>Normally, Monero miners join a "pool" -- a company-run server that
combines many miners' computing power, finds Monero blocks together,
and splits the reward. The downside: you have to trust that company's
server.</p>
<p>P2Pool works differently. There's no company and no central server.
Instead, all the miners are connected to each other directly, and they
keep their own shared record of who did how much work. This shared
record is called the "sidechain." It works a lot like Monero's own
blockchain, just faster and just for tracking mining shares.</p>
<p>Every time your computer solves a small piece of work, that's
called a "share." Shares don't pay out on their own -- they're proof
you were mining. Every so often, purely by luck, one share also happens
to solve a full Monero block. When that happens, the reward gets split
among everyone who had a share recently, in proportion to how much work
they contributed. This payout method is called "PPLNS" (Pay Per Last N
Shares).</p>

<h2>Network Panel (left side)</h2>
<p>This side shows the health of the whole P2Pool network you're
connected to -- not just your own miner.</p>

<h3>P2Pool Height</h3>
<p>The current length of the sidechain (the shared share-record
mentioned above). It climbs quickly -- a new sidechain block gets added
roughly every 10-30 seconds depending on the network -- so this number
moving fast is normal and doesn't mean a Monero block was found.</p>

<h3>P2Pool Hashrate</h3>
<p>The combined computing power of every miner currently on this
P2Pool network, added together. Shown as H/s, kH/s, MH/s etc -- each
step up means 1,000 times more hashes per second, similar to how
1,000 KB makes a MB.</p>

<h3>Hashrate Graph</h3>
<p>A running history of the hashrate number above, since you opened
the program. It only remembers what's happened while the dashboard has
been open -- closing and reopening starts it fresh.</p>

<h3>Time Since Last Block Found</h3>
<p>This counts up live, second by second, from the last time P2Pool
actually found a real Monero block (not a sidechain block -- those
happen constantly and aren't shown here). The exact date and time of
that block is shown underneath in smaller text.</p>

<h3>Average Block Frequency</h3>
<p>How far apart, on average, P2Pool's last few found blocks were.
Because block-finding is based on luck, this number can swing quite a
bit -- it's a rough average, not a prediction.</p>

<h3>Window Miners</h3>
<p>How many different miners currently have at least one share counted
in the active payout window. A rough sense of how "crowded" the pool
is right now.</p>

<h3>Current Payout Per Share</h3>
<p>A rough estimate of what a single share is worth right now, in XMR,
based on recent block rewards. Actual payouts use a more precise,
difficulty-weighted calculation -- this is a simplified estimate for a
quick glance, not an exact figure.</p>

<h3>Last 3 Blocks Found</h3>
<p>The most recent real Monero blocks P2Pool has found, with the date,
time, and total reward for each.</p>

<h2>Wallet Panel (right side)</h2>
<p>This side only fills in if you entered a wallet address at startup.
It shows information specific to that one wallet.</p>

<h3>Wallet not found on P2Pool yet</h3>
<p>If you see this message, don't worry -- it's normal for a wallet
that just started mining. New wallets can take anywhere from a few
hours to a couple of days to show up, depending on luck and how much
hashing power you're contributing.</p>

<h3>Last Share Found</h3>
<p>The most recent time this specific wallet contributed a share to
P2Pool.</p>

<h3>Current Active Shares</h3>
<p>How many of this wallet's shares are still counted in the live
payout window right now. This number naturally goes up as you mine,
and down as older shares expire (see below).</p>

<h3>Shares (Last 24h)</h3>
<p>How many shares this wallet has contributed in roughly the past 24
hours -- a longer view than "Current Active Shares," which only counts
what's still active this moment.</p>

<h3>Estimated Window Reward</h3>
<p>A rough estimate of what this wallet would be paid if a block were
found right now, based on this wallet's share of the current window.
Like "Current Payout Per Share," this is a simplified estimate, not an
exact PPLNS calculation.</p>

<h3>Recent Share Age / Expiration</h3>
<p>Shares don't stay eligible for payout forever -- each one expires
exactly 6 hours after it was found, once the sidechain has moved far
enough past it. This table shows your 3 most recent shares and a live
countdown to when each one expires. Once a share passes 6 hours, this
table will show "Expired" for it instead of a countdown.</p>

<h3>Recent Deposits</h3>
<p>The last 5 actual Monero payouts this wallet has received from
blocks P2Pool found, with the amount and a live-ticking "how long ago"
age for each. If this wallet has fewer than 5 payouts so far, the
remaining rows show "--".</p>

<h2>XMR Price Converter (bottom bar)</h2>
<p>Type any amount of XMR (numbers and a decimal point only) to see
its converted value in USD, GBP, or EUR. Prices come from CoinGecko --
a separate service from P2Pool itself, with its own refresh schedule,
described under "Refresh Behavior" below. Your chosen currency is
remembered for next time you open the program.</p>

<h2>Refresh Behavior</h2>
<p>Most of the numbers on this dashboard update live, the moment
something happens on the P2Pool network -- there's no timer to wait
for and nothing to click. This covers P2Pool Height, P2Pool Hashrate,
the Last 3 Blocks Found table, and everything in the Wallet Panel.</p>
<p>"Window Miners," "Current Payout Per Share," and "Estimated Window
Reward" are the exceptions -- they update whenever a new Monero block
is found, or when you click "Refresh Now," rather than instantly with
every small change. In practice this usually means they're accurate
within the last few minutes to a couple of hours, depending on how
often blocks are being found.</p>
<p>The XMR Price Converter is separate from all of this -- it isn't
part of P2Pool at all, so it checks CoinGecko for new prices every 5
minutes on its own schedule, shown as a countdown near the Refresh
button.</p>
<p>Click "Refresh Now" anytime to re-check everything from scratch.
It's limited to once every 30 seconds, to avoid putting unnecessary
load on the server.</p>

<h2>Startup Screen</h2>
<p>When the program opens, it asks which network to use (Normal,
Mini, or Nano) and, optionally, a wallet address to track. Picking the
wrong network means a wallet that's actually mining elsewhere won't
show any data. Previously used wallets are saved in a dropdown for
next time -- unless you check "Don't remember this wallet," or use the
"Purge Saved Wallets" button to clear all of them at once.</p>

<h2>License</h2>
<p><strong>The Commons Clause Condition to License Work Version 1.0</strong></p>

<h3>1. License Terms: The MIT License (MIT)</h3>
<p>Copyright (c) 2026</p>
<p>Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:</p>
<p>The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.</p>

<h3>2. Commons Clause Condition</h3>
<p>Without limiting other conditions in the License, the grant of rights under
the License will not include, and the License does not grant to you, the right
to Sell the Software.</p>
<p>For purposes of the foregoing, "Sell" means practicing any or all of the rights
granted to you under the License to provide to third parties, for a fee or
other consideration (including without limitation the fee for hosting or
hosting-related services, or fee for support or maintenance services), a product
or service whose value derives entirely or substantially from the functionality
of the Software.</p>

<h3>3. Disclaimer</h3>
<p>THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.</p>
"""
