## Kowalski OS — अपने कंप्यूटर से बात करें

[![CI](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml/badge.svg)](https://github.com/KPbICO6Ou/kowalski-os/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/KPbICO6Ou/kowalski-os/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20%C2%B7%20XFCE-orange.svg)](https://ubuntu.com/)

Kowalski OS एक साधारण Linux डेस्कटॉप को ऐसे डेस्कटॉप में बदल देता है जिससे आप बस बात कर सकते हैं। इसे आसान शब्दों में कहें — टाइप करके या बोलकर — कि कोई फ़ाइल ढूँढो, कोई रिमाइंडर सेट करो, किसी ईमेल का सारांश बताओ, कोई कमांड चलाओ, या स्क्रीन पर जो है उसे देखो। यह सहायक आपकी अपनी मशीन पर **स्थानीय रूप से** चलता है ([Ollama](https://ollama.com) के ज़रिए), इसलिए आपका डेटा कभी आपके कंप्यूटर से बाहर नहीं जाता।

[English](https://github.com/KPbICO6Ou/kowalski-os/blob/main/README.md) | [Español](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ES.md) | [Português](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_PT.md) | [Français](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_DE.md) | [Italiano](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_IT.md) | [Русский](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_RU.md) | [中文](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_ZH.md) | [日本語](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_JA.md) | **[हिन्दी](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_HI.md)** | [한국어](https://github.com/KPbICO6Ou/kowalski-os/blob/main/docs/README_KR.md)

### यह क्या-क्या कर सकता है?

इंस्टॉल करने के बाद, आप इस तरह की बातें टाइप कर सकते हैं:

```bash
kow ask "how much free disk space do I have?"
kow ask "find the budget spreadsheet I edited last week and open it"
kow ask "remind me in 20 minutes to call mom"
kow ask "summarize my latest email from Anna"
kow ask --plan "research topic X, then write a short note about it"
```

- **चीज़ें ढूँढना** — नाम से, सामग्री से, या मतलब से ("उस यात्रा वाला दस्तावेज़")।
- **याद रखना** — नोट्स, रिमाइंडर, और आपके बारे में ऐसी बातें जिन्हें यह बाद में याद कर सके।
- **ईमेल** — खोजना, पढ़ना, ड्राफ़्ट बनाना, और (आपकी मंज़ूरी से) भेजना।
- **आपकी स्क्रीन देखना** — "अभी स्क्रीन पर क्या है?" इसका जवाब देना।
- **काम करना** — ऐप्स खोलना, विंडोज़ नियंत्रित करना, शेल कमांड चलाना, कई-चरणों वाले काम स्वचालित करना।
- **बातचीत** — बिना हाथ लगाए चलने वाला वॉइस मोड (वेक वर्ड → स्पीच-टू-टेक्स्ट → जवाब → टेक्स्ट-टू-स्पीच)।

### क्या यह सुरक्षित है?

हाँ, इसकी बनावट ही ऐसी है:

- सहायक केवल उन्हीं फ़ोल्डरों को छू सकता है जिनकी आप अनुमति देते हैं।
- कोई भी जोखिम भरा काम — ईमेल भेजना, कमांड चलाना, किसी विंडो में टाइप करना — **पहले आपकी पुष्टि माँगता है**, और आप मना कर सकते हैं।
- शेल कमांड Linux पर एक सैंडबॉक्स के अंदर चलते हैं।
- हर क्रिया एक स्थानीय लॉग में लिखी जाती है जिसे आप `kow journal tail` से देख सकते हैं।
- भाषा मॉडल Ollama के ज़रिए स्थानीय रूप से चलता है — कुछ भी क्लाउड पर नहीं भेजा जाता।

### आवश्यकताएँ

- XFCE डेस्कटॉप के साथ **Ubuntu 24.04** (डेवलपमेंट के लिए आप सहायक को macOS पर भी चला सकते हैं)।
- **[Ollama](https://ollama.com)** के साथ एक ऐसा मॉडल जो टूल-कॉलिंग का समर्थन करता हो, जैसे `qwen2.5:14b` (या छोटी मशीन पर `qwen2.5:7b`)।
- तेज़ जवाबों के लिए एक **GPU की सलाह दी जाती है**, लेकिन यह ज़रूरी नहीं है।

### इंस्टॉल करें (Ubuntu)

मुख्य सहायक इंस्टॉल करें और इसे बैकग्राउंड में शुरू करें:

```bash
sudo apt install ./kowalski-core_*.deb        # the assistant + the `kow` command
systemctl --user enable --now kowalski-core   # run it as a background service
```

जब चाहें तब वैकल्पिक घटक जोड़ें:

```bash
sudo apt install ./kowalski-ui_*.deb       # the Omnibox (Super+Space) + desktop theme
sudo apt install ./kowalski-voice_*.deb    # hands-free voice mode
sudo apt install ./kowalski-indexer_*.deb  # semantic file search
```

> अभी तक `.deb` फ़ाइलें नहीं हैं? उन्हें `make deb` से बनाएँ (Docker की ज़रूरत होती है), या नीचे दिए गए डेवलपर सेटअप का उपयोग करें।

### इसे आज़माएँ (डेवलपर सेटअप — Linux या macOS)

```bash
git clone https://github.com/KPbICO6Ou/kowalski-os.git
cd kowalski-os
make venv                       # create a virtualenv with the dev tools
.venv/bin/pip install -e core   # install the assistant core
ollama pull qwen2.5:7b          # download a local model
.venv/bin/kow ask "how much free disk space do I have?"
```

### पहले कदम

```bash
kow ask "..."             # ask once and get an answer
kow ask --plan "..."      # for bigger tasks: it makes a plan and works through it
kow ask --continue "..."  # keep the same conversation going
kow tools list            # see everything the assistant can do
kow journal tail          # see what it has done
kow serve                 # run it as a background service for the desktop apps
```

### यह कैसे व्यवस्थित है

Kowalski OS में एक ही "दिमाग" है — `kow-core` सेवा — जिससे हर इंटरफ़ेस बात करता है: आज कमांड लाइन, और डेस्कटॉप पर Omnibox, वॉइस, और चैट विंडोज़। इसलिए सहायक हर जगह एक जैसा व्यवहार करता है।

| भाग | यह क्या है |
|---|---|
| `core/` | सहायक का दिमाग: अनुरोधों को समझना, टूल्स, सुरक्षा नियम, लॉग |
| `ui/` | Omnibox (Super+Space दबाएँ) और डेस्कटॉप हिस्से |
| `voice/` | वेक वर्ड, स्पीच-टू-टेक्स्ट, टेक्स्ट-टू-स्पीच |
| `indexer/` | सिमेंटिक फ़ाइल खोज |
| `setup/` | पहली बार चलने वाला सेटअप विज़ार्ड |
| `provision/` | वे स्क्रिप्ट जो पूरे सिस्टम को एक नई मशीन पर इंस्टॉल करती हैं |
| `packaging/` | `.deb` पैकेज और डेस्कटॉप थीम |

अधिक जानकारी: [Architecture](docs/ARCHITECTURE.md) · [Installing on a machine](docs/PROVISIONING.md) · [Packaging](docs/PACKAGING.md)।

### प्रोजेक्ट की स्थिति

Kowalski OS **शुरुआती विकास** में है। सहायक आज कमांड लाइन के ज़रिए काम करता है; ग्राफ़िकल डेस्कटॉप हिस्से (Omnibox विंडो, वॉइस, पूरा सिस्टम इंस्टॉलेशन) बने और परखे हुए हैं, लेकिन पूरी तरह जीवंत होने के लिए इन्हें GPU वाली एक असली Linux मशीन की ज़रूरत है। कुछ कमियाँ रहने की उम्मीद रखें।

### लाइसेंस

[Apache-2.0](LICENSE)।
