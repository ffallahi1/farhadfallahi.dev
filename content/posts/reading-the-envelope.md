---
title: "Reading the Envelope: Machine Learning, Metadata, and the Limits of Tor's Anonymity"
date: 2026-09-25
draft: false
author: "Farhad Fallahi"
description: "A literature review of learning-based traffic analysis against Tor (2013–2026): threat models, deep learning attacks, the lab-versus-wild debate, and defenses."
summary: "Tor encrypts what you send, but not the shape of your traffic. A review of how machine learning reads that shape, and whether lab results survive the real Tor network."
tags: ["tor", "anonymity", "traffic-analysis", "machine-learning", "website-fingerprinting", "privacy", "literature-review"]
categories: ["Research"]
ShowToc: true
TocOpen: false
ShowReadingTime: true
ShowWordCount: true
---

*A literature review of learning-based traffic analysis against Tor, 2013–2026*

## Abstract

Tor encrypts *what* you send, but it cannot fully hide the *shape* of your traffic: which direction packets travel, when they travel, and how many there are. Over the past decade, researchers have shown that machine learning models can read that shape well enough to do two things. They can guess which website a Tor user is visiting (website fingerprinting), and they can link the two ends of a Tor connection together (flow correlation).

In this post I review that research. I explain the networking that makes these attacks possible, lay out the threat models they assume, and describe how the major deep learning attacks work. Then I examine the question I think matters most: do the impressive laboratory results hold up on the real Tor network?

My conclusion is that the answer depends less on how clever the model is and more on three things:

- where the attacker sits,
- how rare the thing they are looking for is,
- and a set of quiet assumptions built into most experiments.

## 1. Introduction: the envelope problem

Imagine mailing a sealed letter. The post office can't read it, but it can still see the envelope: how thick it is, when you sent it, and whether a thick reply came back a day later. If you write to the same bank every Friday and always get a two-page reply, someone watching envelopes could guess what's inside without opening anything.

Encrypted network traffic works the same way. Tor wraps your data in several layers of encryption and bounces it across the world, so nobody along the path can read it. But the envelopes still exist: packet timing, direction and volume. This leftover information is called **metadata**, and studying it is called **traffic analysis**.

Traffic analysis against Tor is not new. What changed around 2018 is that researchers started giving the problem to deep learning models. These models are very good at finding patterns in long sequences that humans and older statistical methods miss. Headlines about "AI de-anonymizing Tor" followed. I wanted to know how much of that holds up, so I built this review around three research questions.

**RQ1.** What can an observer actually see in Tor traffic, and who is in a position to see it?

**RQ2.** How does machine learning turn that metadata into de-anonymization, and how much better is it than older methods?

**RQ3.** Do the lab results survive contact with the real Tor network, and what limits them?

**Scope and ethics.** Everything here comes from published peer-reviewed research, Tor Project sources, or public reporting, all cited in the footnotes. I explain attacks at a conceptual level so readers can understand the risks and the defenses. I don't include attack code or step-by-step instructions.

### 1.1 How I conducted this review

I focused on the conferences where most of this research appears: ACM CCS, IEEE S&P, USENIX Security, NDSS and PoPETs. I also used Tor Project primary sources.

I included a paper if it did one of two things:

- introduced a learning-based technique that moved the state of the art, or
- challenged how the field evaluates these attacks.

I deliberately gave the critical papers as much space as the attack papers. A review that only reports headline accuracy would be misleading, and Section 5 explains why.

One warning up front: papers use different datasets, metrics and settings, so their numbers are not directly comparable. I compare trends and arguments, not leaderboard rankings.

## 2. Background: what Tor hides, and what it can't

### 2.1 Onion routing in brief

Tor's original design is described in Dingledine, Mathewson and Syverson's 2004 paper.[^dingledine2004] By default, a Tor client builds a circuit through three relays: an entry guard, a middle relay, and an exit. Traffic is wrapped in layers of encryption and each relay removes only its own layer, so each relay knows only the hop before it and the hop after it, not the content or both endpoints. Neighbouring relays communicate over TLS connections, and Tor regularly retires old circuits and builds new ones, typically about every ten minutes.[^wu2025] Data travels in fixed-size units called cells, each roughly 512 bytes.[^shadbeh2026] The network itself is made up of roughly 10,700 volunteer-run relays.[^relaycount]

```text
             (A)               (B)                          (C)              (D)
  You ──► Your ISP ──► Guard relay ──► Middle relay ──► Exit relay ──► Site's ISP ──► Website
          sees your IP  sees your IP    sees neither     sees the
          + traffic     + traffic       endpoint         destination
          shape         shape                            + traffic shape
```

The design goal is that no single point on this path sees both who you are and where you are going. The guard knows your IP address but not your destination, while the exit connects to the destination without knowing your IP.[^shadbeh2026] Your ISP is in the same position as the guard. De-anonymization means linking those two halves.

### 2.2 Three details that matter later

**Guards are sticky.** A client picks a small set of entry guards and keeps them for a long time, typically months.[^shadbeh2026] This is deliberate. Reusing guards for a set period lowers the cumulative risk of eventually picking a compromised entry.[^holland2024] The trade-off is that a malicious guard can observe both a client's IP address and their traffic patterns over long periods.[^shadbeh2026]

**Onion services hide both sides.** When you visit a `.onion` site, Tor sets up an encrypted session between the client and the service through an intermediate relay called the rendezvous point, which forwards packets without revealing either side's IP address.[^lopes2024]

**Conflux splits traffic.** Since Tor 0.4.8.4, Conflux can divide one connection across two circuits ("legs") that share the same exit but usually use different guards and middle relays.[^shadbeh2026] It was built to improve performance, but as Section 6 shows, it also changes what an attacker at a guard can see.

### 2.3 The promise Tor never made

Tor is a low-latency network built for interactive browsing. Its relays avoid disguising packet timing because doing so would slow connections, and this is exactly why Tor is known to be vulnerable to flow correlation.[^nasr2018]

The Tor Project has been open about this limit. It separates traffic analysis, where an attacker tries to figure out whom to investigate, from traffic confirmation, where an attacker watches the right network locations to test a specific suspicion. Tor aims to resist the first but cannot protect against the second.[^torblog-onecell] The same post points to earlier research that achieved confident correlation while sampling only one packet in two thousand on each side.[^torblog-onecell][^murdoch2007] In addition, Tor's design does not protect against a global passive adversary who watches and measures traffic entering and leaving the network and correlates both sides.[^torblog-netflows]

This context matters when judging "AI breaks Tor" claims. An attack that needs a view of both ends isn't breaking a promise Tor made; it's working in territory Tor openly says it can't defend. The more interesting question is how much *less* than a global view an attacker needs once machine learning is involved.

### 2.4 What an attacker actually sees

Content is encrypted and cells are equal in size, so most attacks reduce a connection to a sequence of directions and times. A common representation ignores packet size and timestamps and keeps only direction, with +1 for outgoing and −1 for incoming.[^sirinam2019] A page load might look like this:

```text
+1 +1 -1 -1 -1 -1 -1 -1 +1 -1 -1 -1 -1 -1 -1 -1 -1 -1 +1 +1 -1 -1 ...
└req┘ └──── response burst ────┘ └────── larger burst ──────┘
```

Each page has its own layout of HTML, images and scripts, so different pages produce different rhythms of small requests and large response bursts. That rhythm is the "fingerprint".

## 3. Threat model

A threat model states who the attacker is, where they sit, what they can do and what they want. Every result in this field is only valid inside its threat model, so this section matters.

### 3.1 Attacker positions

| Adversary | Position | What they observe | Main attack |
|---|---|---|---|
| Local observer (ISP, campus Wi-Fi, employer) | Between user and guard | User's IP and the encrypted traffic shape | Website fingerprinting |
| Malicious guard relay | First hop | User's IP, per-circuit cell timing, circuit IDs | Website fingerprinting (stronger form) |
| Operator of relays at both ends | Guard and exit | Both halves of some circuits | Flow correlation |
| Autonomous System (AS) or Internet Exchange Point (IXP) | Internet backbone | Parts of many users' traffic on both sides | Flow correlation, routing attacks |
| Colluding ISPs across countries | Several access networks | Client side and onion-service side | Onion-service correlation |

Research models Tor's realistic adversary as having partial visibility. This adversary sees only some network links, can inject or modify traffic on those links, and may run malicious relays.[^onionintro2026] For fingerprinting, the attacker sits on the client's access link or runs the guard, so they already know the client's identity and want to recover the hidden destination.[^shadbeh2026]

**Backbone attackers.** The internet is made of Autonomous Systems, which are networks run by ISPs, universities and cloud providers. They exchange routes using a protocol called BGP. Routes are often asymmetric: the path from A to B is not always the path from B to A. The RAPTOR study showed three ways an AS can gain visibility:[^sun2015]

- exploit asymmetric routing to see at least one direction of a user's traffic at each end,
- benefit from routing changes over time to end up on more users' paths,
- and manipulate routing through BGP hijacks and interceptions.

Their measurements confirmed that traffic analysis still works when the attacker sees only one direction of traffic.[^sun2015]

**Relay-running attackers** are not hypothetical. An unidentified actor tracked as KAX17 ran more than 900 malicious relays at its peak. At one point, a user had about a 16% chance of entering Tor through one of its guards and a 35% chance of passing through one of its middle relays.[^therecord-kax17][^nusenu2021]

### 3.2 Two goals, two families of attacks

**Website fingerprinting (WF)** answers: *"I know who this user is. Which website are they visiting?"* It needs only one vantage point near the user.

**Flow correlation** answers: *"I see a flow entering Tor and a flow leaving Tor. Do they belong to the same connection?"* It needs vantage points at both ends, but it can reveal both the user and the destination.

### 3.3 The fine print: assumptions most experiments make

This table is the core of my critical framework. Each row is a simplification that makes experiments easier to run and usually makes the attack look stronger. Section 6 returns to the evidence for each row.

| Assumption | Why it helps the attacker | What reality looks like |
|---|---|---|
| **Closed world:** the user visits only sites the attacker trained on | The model never has to answer "none of the above" | Users visit millions of sites the attacker has never seen |
| **One clean page load at a time** | Each trace has a clear start and end | People open multiple tabs and have background activity |
| **Same network for training and testing** | Timing patterns match | Latency differs across users, relays and time of day |
| **Fresh training data** | The site still looks like it did during training | Websites change, so models decay ("concept drift") |
| **Attacker sees the full trace** | No features are missing | Conflux splits traffic, and captures can be partial |
| **Every entry flow has a matching exit flow** (correlation) | Matching becomes a closed puzzle | Most observed flows have no visible partner |
| **Scripted browsers behave like humans** | Data is cheap to collect | Real users click, scroll and navigate unpredictably |

## 4. How machine learning reads the envelope

### 4.1 Why machine learning fits this problem

Earlier fingerprinting attacks depended on researchers hand-designing features, such as burst counts or total bytes, and feeding them to classic classifiers. For example, k-fingerprinting (k-FP) used a random forest over a large set of handcrafted traffic features.[^hayes2016][^shadbeh2026]

Deep learning reverses this. You give the model the raw sequence and let it discover which patterns matter. When the signal is hidden in long, noisy sequences, that is a major advantage.

### 4.2 Website fingerprinting

The typical pipeline looks like supervised learning in any other field:

1. The attacker chooses a list of "monitored" websites.
2. They load each site many times through Tor Browser while recording the traffic.
3. They convert each recording into a direction (and sometimes timing) sequence.
4. They train a classifier to map sequences to website labels.
5. They apply that classifier to a victim's traffic.

**Deep Fingerprinting (DF, 2018)** was the turning point. It used a **convolutional neural network (CNN)**. You can think of a CNN as a set of small pattern detectors sliding along the sequence. Each one learns a shape such as "short request followed by a long download burst", and deeper layers combine those shapes into page-level patterns.

The results were striking:[^sirinam2018]

- Over 98% accuracy on undefended Tor traffic.
- More than 90% accuracy against the WTF-PAD defense,[^juarez2016] the only attack that was effective against it at the time.
- Only 49.7% accuracy against another defense, Walkie-Talkie.
- 0.99 precision and 0.94 recall on undefended traffic in the more realistic open-world setting.

The attacker model was modest: a passive observer who sees only the timing and direction of packets.[^sirinam2018]

**Triplet Fingerprinting (2019)** attacked a practical weakness: DF needed large amounts of training data that had to be refreshed regularly. Instead of learning "this is site #37", a triplet network learns *similarity*. It trains on sets of three traces: an anchor, a matching trace and a non-matching trace. Traces from the same site end up close together. This enabled N-shot learning, a technique that needs only a few training samples to recognize a class.[^sirinam2019]

**Multi-tab attacks (2023 onward)** targeted the "one page at a time" assumption. ARES treats a browsing session as a multi-label classification problem and uses a Transformer model that recognizes websites from local patterns across multiple traffic segments. Transformers are the same family of architecture behind modern language models. Its authors report mean average precision above 0.9 and more than double the baselines' performance under the WTF-PAD defense.[^deng2023]

**LLM agents as data generators (2025)** show a newer way AI enters the picture. Song et al. argue that single-page applications break the idea of a website as a set of separate pages, and that scripted browsers don't produce the rich behaviour of real users. Their proposal replaces session boundaries with continuous traffic segments and uses large language model agents to generate data at scale.[^song2025] Here the AI is not the classifier; it simulates the users the classifier learns from.

### 4.3 Flow correlation

Flow correlation compares a flow seen entering Tor with a flow seen leaving it. Before deep learning, this was done with general-purpose statistics such as correlation coefficients.

**DeepCorr (2018)** replaced those generic formulas with a correlation function learned from data. Using about 900 packets per flow, it reported 96% correlation accuracy, compared with 4% for RAPTOR's method in the same setting. The costs are worth noting: it was trained on 25,000 self-generated Tor flows, training took about a day on one GPU, and the authors estimated an attacker would need to retrain roughly once a month.[^nasr2018]

**DeepCoFFEA (2022)** addressed a scaling problem that Section 5 works through with numbers. Checking every entry flow against every exit flow means comparing N² pairs. This causes a computational explosion and a shrinking base rate, which leads to either many false positives or very few correct matches.[^oh2022]

DeepCoFFEA combined two ideas:[^oh2022]

- **Embeddings.** Two neural networks map entry flows and exit flows into a shared low-dimensional space where matching flows land close together. Comparing these points is much cheaper than comparing full traces.
- **Amplification.** Each flow is split into short windows, and a match must win a vote across the windows, which sharply reduces false positives. The analogy is witnesses: one witness can be wrong, but a false match that fools many independent witnesses is much less likely.

Tuned for high precision, it reached a 93% true positive rate versus at most 13% for earlier attacks, and ran about a hundred times faster.[^oh2022]

**RECTor (2025)** targets two more assumptions: that the attacker captures complete flows, and that every entry flow has a matching exit flow. It splits flows into windows, uses attention to focus on the most informative ones, and replaces all-pairs comparison with approximate nearest-neighbour search. This makes its cost grow almost linearly with the number of flows.[^wu2025]

Its results: 85% TPR at 20% FPR under moderate noise, and 70% TPR at 20% FPR under heavy noise, where only 10% of observed flows had a true partner.[^wu2025] Keep that 20% figure in mind; Section 5 explains why it matters.

**SUMo (2024)** is my favourite counterexample. It is a flow correlation attack on onion services designed for a group of colluding ISPs. They collect Tor traffic at several points and analyze it with machine learning classifiers plus a similarity function based on the classic subset-sum problem. But first, the authors tried retraining DeepCorr on onion-service traffic and the model failed to converge. The heavy resource requirements pushed them away from deep learning toward more scalable techniques.[^lopes2024] "AI" does not automatically win; the structure of the problem matters.

### 4.4 Milestones at a glance

| Year | Work | Family | Core idea |
|---|---|---|---|
| 2015 | RAPTOR | Correlation | Routing asymmetry and BGP manipulation expand what an AS can see |
| 2016 | k-FP | Fingerprinting | Random forest over handcrafted features |
| 2018 | Deep Fingerprinting | Fingerprinting | CNN learns features from raw direction sequences |
| 2018 | DeepCorr | Correlation | CNN learns a correlation function |
| 2019 | Triplet Fingerprinting | Fingerprinting | Learns similarity, needs only a few samples per site |
| 2022 | DeepCoFFEA | Correlation | Embeddings plus window voting to cut false positives |
| 2023 | ARES | Fingerprinting | Transformer, multi-tab browsing as a multi-label problem |
| 2024 | SUMo | Correlation | Colluding ISPs, onion services, subset-sum similarity |
| 2025 | RECTor | Correlation | Attention over windows, partial observations, near-linear search |
| 2025 | Multi-agent LLM WF | Fingerprinting | LLM agents generate realistic browsing data |

Sources for each row are cited in Sections 3 and 4 above.

## 5. How success is measured, and why "accuracy" misleads

### 5.1 Closed world versus open world

In a closed world, the client visits only monitored destinations, so the task is ordinary multi-class classification. In an open world, the client may also visit other sites, and the attacker must either identify a monitored site or reject the trace as non-monitored. Open-world evaluations must account for how rarely monitored sites are actually visited, and they are widely seen as the more realistic benchmark.[^shadbeh2026]

Four terms matter:

- **True positive rate (TPR, also called recall):** the fraction of real visits to monitored sites that the model catches.
- **False positive rate (FPR):** the fraction of innocent traffic the model wrongly flags.
- **Precision:** the fraction of the model's alerts that are actually correct.
- **Base rate:** how common the thing you are looking for is in the first place.

### 5.2 Worked example: the base-rate trap in fingerprinting

These numbers are my own illustration, chosen to fall in the same range as published results.

**Scenario 1.** An observer watches one million Tor page loads per day and wants to detect visits to one sensitive site.

- 1 in 1,000 loads (1,000 in total) actually go to that site.
- The classifier has 95% TPR and 0.5% FPR, which sounds excellent.
- It correctly flags 950 of the 1,000 real visits.
- It also examines the other 999,000 loads and wrongly flags 0.5% of them: **4,995 false alarms**.
- Only 950 of the 5,945 alerts are real, so **precision is about 16%**. More than five out of every six alerts point at an innocent person.

**Scenario 2.** The same classifier, but the site is rarer: 1 in 100,000 loads (10 visits per day). The model catches about 9.5 real visits and raises about 5,000 false alarms, so precision falls to roughly **0.2%**.

**Scenario 3.** Back to Scenario 1, but FPR is cut tenfold to 0.05%. False alarms drop to about 500, and precision rises to around **66%**.

In the open world, **FPR dominates**. Raising accuracy from 95% to 99% barely matters if FPR stays the same, while shaving a fraction of a percent off FPR can transform an attack.

This is called the base-rate fallacy, and the field has known about it for a long time. Juarez et al. showed in 2014 that earlier work fell into it in the open-world setting; adding a verification step cut false positives by more than 63% but didn't solve the problem.[^juarez2014] Work on genuine Tor traces (the GTT23 dataset) reached a similar conclusion: precisely fingerprinting most websites in real Tor traffic would need false positive rates orders of magnitude lower than those needed on standard lab datasets.[^jansen2024]

### 5.3 Worked example: why correlation needs amplification

Flow correlation has the same problem in a sharper form.

- An attacker sees 10,000 flows entering Tor and 10,000 flows leaving during the same time window.
- Only 10,000 pairs are true matches, but there are 100,000,000 possible pairs.
- With 90% TPR and 0.1% FPR, the attacker finds 9,000 true matches and about **99,990 false ones**.
- Roughly 11 of every 12 claimed links are wrong (precision around 8%).

This is why DeepCoFFEA's window voting matters, and why I flagged RECTor's result. A 20% FPR is only usable when something has already shrunk the candidate set dramatically, which is what RECTor's approach of comparing each flow only against a few nearby clusters tries to do.[^wu2025] When reading any correlation paper, the first thing to check is how many candidate pairs the reported FPR is applied to.

## 6. The lab versus the wild

This is where the literature gets genuinely interesting, because careful researchers have reached conflicting conclusions.

### 6.1 The skeptical case

The Tor Project's own researchers were early skeptics. In 2013, Mike Perry argued that fairly simple defenses would substantially raise false positive rates once attacks were run against many pages, lots of background traffic and many users.[^perry2013] Juarez et al. (2014) then ran attacks with the usual assumptions removed. They found that factors normally left out of the model, such as users' browsing habits, their location and their Tor Browser version, had a significant effect on attack success.[^juarez2014]

The strongest skeptical result came from Cherubin, Jansen and Troncoso (2022). They ran the first website fingerprinting evaluation that used genuine Tor traffic as ground truth in a true open world, training on data safely collected at a Tor exit relay. The attack exceeded 95% accuracy when monitoring five popular websites, but fell below 80% with as few as 25 sites. The authors concluded that real-world fingerprinting is likely infeasible beyond a small set of sites.[^cherubin2022]

### 6.2 The rebuttal

In March 2026, researchers at Simon Fraser University revisited the question from a different vantage point: a Tor guard relay they operated. Their privacy-preserving method built the open world from real, unlabeled Tor traffic and paired it with synthetic traces of monitored pages, producing a dataset of over 800,000 traces. The best-performing attack achieved 0.956 precision and 0.922 recall at a 9% base rate.[^shadbeh2026]

The authors point to three methodological differences to explain the disagreement. Cherubin et al. trained on exit-side traces but tested on entry-side traces, used domain labels instead of page labels, and in their final results sometimes had as few as 10 training traces for a class. Domain labels lump many different pages into one class, which makes them harder to classify.[^shadbeh2026]

In other words, the two studies modelled different attackers. Cherubin's attacker was handicapped by choices a real attacker would not have to make. The 2026 attacker sat at the guard with carefully labelled training data.

### 6.3 What the rebuttal also revealed

The 2026 paper is not simply "fingerprinting works". Several of its findings support the assumptions table in Section 3.3.[^shadbeh2026]

**The guard's seat is special.** A guard can see circuit IDs, and Tor Browser puts each first-party domain on its own circuit. That lets a guard separate simultaneous page loads that an ISP would see mixed together. For guards, this largely removes the multi-tab problem; for ISPs, it does not.

**Timing features are fragile.** When the training and testing clients were on different networks (Australia and Canada), models that relied heavily on timing collapsed. Deep Fingerprinting, which uses only packet direction, stayed the strongest. Newer is not always more robust.

**Models decay.** Every model lost performance over six months as websites changed. For the most drift-resistant model, the decline came mainly from missing more visits (lower recall), while its alerts stayed mostly reliable.

**Conflux is an accidental defense, with a loophole.** Its effect is large:

- When the guard saw only one of the two Conflux legs, DF's F1 score dropped from 0.939 to 0.379. (F1 is a single score that combines precision and recall.)
- But Conflux's default scheduler, LowRTT, prefers the leg with the lowest round-trip time. Leg switches often happen after only about 50 KB, a figure tied to Tor sending a SENDME flow-control cell every 100 cells.
- So a guard with a latency advantage tends to carry the feature-rich start of each page load. Simulating such a "powerful guard" raised recall from 0.522 to 0.881 at a 0.5% FPR.

This is a good example of how a transport-layer performance feature quietly shapes privacy.

**Scripted traffic may overstate performance.** The LLM-agent study found that users behave very differently even on the same website, which makes fingerprinting harder than assumed and calls for larger, more representative datasets.[^song2025]

### 6.4 My reading of the debate

Both sides are right about different attackers.

Website fingerprinting looks like a credible **targeted confirmation tool** for an adversary who controls a guard, trains carefully on a *small* list of specific pages, and retrains as those pages change. It looks much weaker as a **mass-surveillance tool** that tries to label everything everyone does.

The single biggest variable is not the neural network. It's the attacker's position.

## 7. What real-world de-anonymization has actually looked like

The best-documented recent case did not involve a new neural network. Germany's Federal Criminal Police Office (BKA) was investigating the darknet child-abuse platform "Boystown" between 2019 and 2021:

- The BKA identified Tor nodes used by one of the platform's administrators by tracking nodes connected to the Ricochet chat service.[^german-securityaffairs]
- A Frankfurt court then ordered Telefónica to trace o2 customers who had connected to those nodes, which led to an arrest.[^german-securityaffairs]
- Reporting said authorities monitored individual Tor relays, sometimes for years, and statistically correlated Tor traffic timing with ISP data.[^german-packetlabs]
- A Chaos Computer Club spokesperson said the evidence strongly suggested timing analysis had been used repeatedly over several years against selected Tor users.[^german-securityaffairs]

The Tor Project's response was specific. It believes a user of the long-retired Ricochet application was de-anonymized through a guard discovery attack, which was possible because that version had neither Vanguards-lite nor the vanguards add-on.[^german-securityweek] A guard discovery attack is one where the attacker works out which guard a target uses.

Vanguards-lite, released in Tor 0.4.7, stops an attacker from forcing circuit creation and using a hidden signal to confirm that a malicious middle relay sits next to the user's guard. Once the guard is known, netflow connection times can reveal the user.[^german-securityweek] Netflow records are summaries ISPs keep of which IP addresses connected to which, and when. The Project also noted that a Tor Browser user who doesn't keep a connection open for a long time is less exposed to this kind of timing analysis.[^german-riskybiz]

Three lessons stand out:

- The attack combined long-term relay monitoring, legal access to ISP records and outdated client software, not a cutting-edge classifier.
- Its target was a long-lived, always-on service, which is the ideal case for timing analysis.
- The protection existed before the arrest; the user simply wasn't running software that had it.

Machine learning raises the ceiling of what a well-resourced attacker can do. But in the one well-documented case, success came from persistence, access and an operational mistake.

## 8. Defenses: the other side of the arms race

### 8.1 Padding and delay

The basic defense is to change the envelope. Defenders add dummy cells (**padding**) and hold back real ones (**delays**) so different pages look alike. The catch is cost. The strong link-padding defenses of the time slowed page loads by two to four times and added 40% to 350% bandwidth overhead, which is not acceptable for Tor.[^juarez2016] Tor runs on volunteer bandwidth, so every padding cell is paid for by everyone.

Tor's defensive tooling has a clear lineage: Adaptive Padding (2006) led to WTF-PAD (2016), which led to Tor's Circuit Padding Framework (2019), which led to Maybenot.[^maybenot-github] The current framework has a limit: Tor's C implementation cannot delay packets, which rules out many effective defenses proposed by researchers. A 2023 study stated that no website fingerprinting defenses were deployed in Tor at that time.[^witwer2023]

**Maybenot** generalizes the older framework. It expresses defenses as probabilistic state machines that schedule padding or block outgoing traffic, and it is written in Rust as a library.[^pulls2023] Rust matters because Tor is being rewritten in Rust as **Arti**. As of January 2026, Arti can run as a Tor client and supports onion services, but it cannot yet act as a relay.[^arti2026]

The Maybenot authors give two reasons defenses have lagged: the performance cost of padding and added latency, and the fact that deep learning keeps changing what attacks can do.[^pulls2023] DeepCoFFEA's authors likewise found existing lightweight defenses insufficient against their attack.[^oh2022]

### 8.2 Fighting AI with AI

If attackers use neural networks, defenders can exploit a known weakness of neural networks: **adversarial examples**. These are small changes to an input that cause a model to misclassify it. The Mockingbird defense cut the accuracy of a state-of-the-art attack that had been hardened with adversarial training from 95% to between 29% and 57%, with about 56% bandwidth overhead.[^rahman2021]

The phrase "hardened with adversarial training" is the catch. The attacker can retrain on defended traffic, so adversarial defenses must hold up against an attacker who knows the defense exists.

### 8.3 Network and protocol defenses

Some of the most effective defenses have nothing to do with padding:

- **Sticky guards** reduce the cumulative chance of ever using a malicious entry. This is the Tor Project's main answer to relay-running attackers.[^holland2024]
- **Vanguards** protect against the guard discovery attacks behind the German case. Vanguards-lite is built into Tor from version 0.4.7.[^german-securityweek]
- **Routing monitoring** targets backbone attackers. The RAPTOR authors proposed BGP monitoring to detect routing attacks and traceroute monitoring to detect anomalies in how data actually travels.[^sun2015]
- **Conflux** shows that transport-layer design can help or hurt privacy depending on how traffic is scheduled.[^shadbeh2026]

## 9. Discussion: three findings

**Finding 1: the attacker's position matters more than the model.** In both attack families, what the attacker can see changes results more than switching model architectures does. That includes whether they see the full trace or one Conflux leg, circuit IDs or a mixed stream, one end or both, and complete flows or fragments. For an attacker, the best upgrade is a better seat, not a bigger network.

**Finding 2: false positive rate, not accuracy, decides whether an attack scales.** The base-rate math in Section 5 applies to every paper in this review. Whenever I read a new result, I now ask three questions:

- What is the FPR?
- What is the base rate?
- How many candidates is that FPR applied to?

**Finding 3: machine learning raises the ceiling, operations set the floor.** Deep learning has made attacks far more accurate under controlled conditions. But the documented real-world case relied on long-term monitoring, legal access to ISP data and outdated software.

For everyday users, the practical takeaways are unglamorous:

- Keep Tor Browser and Tor-based apps updated. Protections like Vanguards-lite only help if you are running them.
- Long-lived, always-on connections are the easiest targets for timing analysis.
- Tor still defends well against the most common adversaries, while openly not defending against someone who can watch both ends.

## 10. Limitations of this review

This is a literature review, not an experiment, and it has several limits:

- I haven't reproduced any attack, so I rely on the authors' reported methods and results.
- Papers use different datasets, metrics and settings, so cross-paper numbers are indicative rather than directly comparable.
- The field probably has a publication bias toward successful attacks.
- The methods in the German case are only partly public. The Tor Project said it had not received the technical details and was left with more questions than answers.[^german-securityweek]
- This area moves quickly, so some findings here may be outdated by the time you read this.

## 11. Conclusion

Tor's encryption is not the weak point; its envelopes are. Machine learning has made reading those envelopes far more accurate, from DeepCorr and Deep Fingerprinting in 2018 to attention-based and LLM-assisted methods today.

But the research also shows that headline accuracy depends on assumptions: where the attacker sits, how rare their target is, and how neatly users behave. The most honest summary I can give is this. AI has turned traffic analysis into a serious *targeted* threat for a well-positioned adversary, but it has not made Tor transparent. The defenses most likely to matter are protocol-level decisions about what attackers get to see in the first place.

---

*Web sources were last accessed in September 2026. If you spot an error or a newer result I should include, contact me at security@farhadfallahi.dev.*

## References

[^dingledine2004]: R. Dingledine, N. Mathewson, and P. Syverson. "Tor: The Second-Generation Onion Router." *13th USENIX Security Symposium*, 2004.

[^wu2025]: B. Wu, D. M. Divakaran, L. Csikor, and M. Gurusamy. "RECTor: Robust and Efficient Correlation Attack on Tor." arXiv:2512.00436, 2025 (accepted to *IEEE Communications Magazine*). <https://arxiv.org/pdf/2512.00436>

[^shadbeh2026]: M. Shadbeh, K. Khajavi, and T. Wang. "Reality Check for Tor Website Fingerprinting in the Open World." arXiv:2603.07412, 2026. <https://arxiv.org/pdf/2603.07412>. Dataset: <https://doi.org/10.17605/OSF.IO/9M8EA>

[^relaycount]: 1AEO. "Tor Network Health Dashboard" (third-party dashboard built on Tor Project data), accessed September 2026. <https://metrics.1aeo.com/network-health>

[^holland2024]: J. K. Holland, J. Carpenter, S. E. Oh, and N. Hopper. "DeTorrent: An Adversarial Padding-only Traffic Analysis Defense." *Proceedings on Privacy Enhancing Technologies (PoPETs)*, 2024(1). <https://arxiv.org/pdf/2302.02012>

[^lopes2024]: D. Lopes, J.-D. Dong, P. Medeiros, D. Castro, D. Barradas, B. Portela, J. Vinagre, B. Ferreira, N. Christin, and N. Santos. "Flow Correlation Attacks on Tor Onion Service Sessions with Sliding Subset Sum." *NDSS Symposium*, 2024. <https://doi.org/10.14722/ndss.2024.24337>. Paper: <https://www.ndss-symposium.org/wp-content/uploads/2024-337-paper.pdf>

[^nasr2018]: M. Nasr, A. Bahramali, and A. Houmansadr. "DeepCorr: Strong Flow Correlation Attacks on Tor Using Deep Learning." *ACM CCS*, 2018. <https://arxiv.org/abs/1808.07285>

[^torblog-onecell]: Tor Project. "'One cell is enough to break Tor's anonymity'." *Tor Blog*, 2014. <https://blog.torproject.org/one-cell-enough-break-tors-anonymity/>

[^murdoch2007]: S. J. Murdoch and P. Zieliński. "Sampled Traffic Analysis by Internet-Exchange-Level Adversaries." *Privacy Enhancing Technologies (PET)*, 2007.

[^torblog-netflows]: Tor Project. "Quick Summary of recent traffic correlation using netflows." *Tor Blog*. <https://blog.torproject.org/quick-summary-recent-traffic-correlation-using-netflows/>

[^sirinam2019]: P. Sirinam, N. Mathews, M. S. Rahman, and M. Wright. "Triplet Fingerprinting: More Practical and Portable Website Fingerprinting with N-shot Learning." *ACM CCS*, 2019. <https://doi.org/10.1145/3319535.3354217>. Code and data: <https://github.com/triplet-fingerprinting/tf>

[^onionintro2026]: "A traffic analysis attack against Introduction Protocol and Onion Services," Section 4 (Threat Model). arXiv:2602.23560, 2026. <https://arxiv.org/pdf/2602.23560>

[^sun2015]: Y. Sun, A. Edmundson, L. Vanbever, O. Li, J. Rexford, M. Chiang, and P. Mittal. "RAPTOR: Routing Attacks on Privacy in Tor." *24th USENIX Security Symposium*, 2015. <https://www.usenix.org/conference/usenixsecurity15/technical-sessions/presentation/sun>

[^therecord-kax17]: "A mysterious threat actor is running hundreds of malicious Tor relays." *The Record by Recorded Future*. <https://therecord.media/a-mysterious-threat-actor-is-running-hundreds-of-malicious-tor-relays>

[^nusenu2021]: nusenu. "Is 'KAX17' performing de-anonymization Attacks against Tor Users?" *Medium*, December 2021. <https://nusenu.medium.com/is-kax17-performing-de-anonymization-attacks-against-tor-users-42e566defce8>

[^hayes2016]: J. Hayes and G. Danezis. "k-fingerprinting: A Robust Scalable Website Fingerprinting Technique." *25th USENIX Security Symposium*, 2016.

[^sirinam2018]: P. Sirinam, M. Imani, M. Juarez, and M. Wright. "Deep Fingerprinting: Undermining Website Fingerprinting Defenses with Deep Learning." *ACM CCS*, 2018. <https://doi.org/10.1145/3243734.3243768>. Preprint: <https://arxiv.org/abs/1801.02265>

[^juarez2016]: M. Juarez, M. Imani, M. Perry, C. Diaz, and M. Wright. "Toward an Efficient Website Fingerprinting Defense" (WTF-PAD). *ESORICS*, 2016. <https://arxiv.org/pdf/1512.00524>

[^deng2023]: X. Deng, Q. Yin, Z. Liu, X. Zhao, Q. Li, M. Xu, K. Xu, and J. Wu. "Robust Multi-tab Website Fingerprinting Attacks in the Wild." *IEEE S&P*, 2023. Extended version: "Towards Robust Multi-tab Website Fingerprinting," arXiv:2501.12622. <https://arxiv.org/abs/2501.12622>

[^song2025]: C. Song, D. D. M. Mekala, H. Wang, and R. Martin. "Redefining Website Fingerprinting Attacks With Multiagent LLMs." arXiv:2509.12462, 2025. <https://arxiv.org/abs/2509.12462>

[^oh2022]: S. E. Oh, T. Yang, N. Mathews, J. K. Holland, M. S. Rahman, N. Hopper, and M. Wright. "DeepCoFFEA: Improved Flow Correlation Attacks on Tor via Metric Learning and Amplification." *IEEE S&P*, 2022, pp. 1915–1932. <https://ieeexplore.ieee.org/document/9833801/>. Open-access copy: <https://par.nsf.gov/servlets/purl/10348312>

[^juarez2014]: M. Juarez, S. Afroz, G. Acar, C. Diaz, and R. Greenstadt. "A Critical Evaluation of Website Fingerprinting Attacks." *ACM CCS*, 2014, pp. 263–274. <https://doi.org/10.1145/2660267.2660368>

[^jansen2024]: R. Jansen, R. Wails, and A. Johnson. "A Measurement of Genuine Tor Traces for Realistic Website Fingerprinting" (GTT23). arXiv:2404.07892, 2024. <https://arxiv.org/html/2404.07892>

[^perry2013]: M. Perry. "A Critique of Website Traffic Fingerprinting Attacks." *Tor Blog*, November 2013. <https://blog.torproject.org/critique-website-traffic-fingerprinting-attacks/>. Summary: <https://lwn.net/Articles/573350/>

[^cherubin2022]: G. Cherubin, R. Jansen, and C. Troncoso. "Online Website Fingerprinting: Evaluating Website Fingerprinting Attacks on Tor in the Real World." *31st USENIX Security Symposium*, 2022, pp. 753–770. <https://www.usenix.org/conference/usenixsecurity22/presentation/cherubin>

[^german-securityaffairs]: Security Affairs. "The Tor Project responded to claims that law enforcement can deanonymize Tor users." September 2024. <https://securityaffairs.com/168667/security/tor-project-commented-on-deanonymizing-technique.html>

[^german-packetlabs]: Packetlabs. "German Authorities Claim to De-Anonymize Tor Users Via Timing Analysis." September 2024. <https://www.packetlabs.net/posts/german-authorities-claim-to-de-anonymize-tor-users-via-timing-analysis/>

[^german-securityweek]: SecurityWeek. "Tor Responds to Reports of German Police Deanonymizing Users." September 2024 (quoting the Tor Project's official statement). <https://www.securityweek.com/tor-responds-to-reports-of-german-police-deanonymizing-users/>

[^german-riskybiz]: Risky Business News. "Tor Project plays down deanon attacks in Germany." September 2024. <https://news.risky.biz/risky-biz-news-tor-project-plays-down-deanon-attacks-in-germany/>

[^maybenot-github]: Maybenot project. "Maybenot: a framework for traffic analysis defenses" (README, history of the design). <https://github.com/maybenot-io/maybenot>

[^witwer2023]: E. Witwer et al. "State Machine Frameworks for Website Fingerprinting Defenses: Maybe Not." arXiv:2310.10789, 2023. <https://arxiv.org/pdf/2310.10789>

[^pulls2023]: T. Pulls and E. Witwer. "Maybenot: A Framework for Traffic Analysis Defenses." *ACM Workshop on Privacy in the Electronic Society (WPES)*, 2023. <https://doi.org/10.1145/3603216.3624953>. Preprint: <https://arxiv.org/abs/2304.09510>

[^arti2026]: Tor Project. "Arti: Frequently Asked Questions" (status as of January 2026). <https://arti.torproject.org/FAQs>

[^rahman2021]: M. S. Rahman, M. Imani, N. Mathews, and M. Wright. "Mockingbird: Defending Against Deep-Learning-Based Website Fingerprinting Attacks with Adversarial Traces." *IEEE Transactions on Information Forensics and Security*, 2021. <https://arxiv.org/abs/1902.06626>
