"""What the chatbot says, in English, Sinhala and Tamil, and how member replies are read.

Row names in the member summary come from Palmera's own 'Mapping' sheet (the official
Sinhala/Tamil wording their teams already use). Every other Sinhala/Tamil sentence is
a draft: the ones marked `# native check` must be checked by a native speaker at
Palmera before the pilot. Members are rural women reading on a phone: short
sentences, one idea each, no jargon.

Every message is built in the member's language AND in English (`Reply.en`), so the
dashboard can show an English line under each Sinhala/Tamil bubble for presenters,
judges and officers who don't read the script.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from .aggregate import to_monthly
from .models import FormRecord
from .schema import Template

LANGS = ("en", "si", "ta")

# One currency style per language, used the same way in the summary and the receipt.
CURRENCY = {"en": "Rs.", "si": "රු.", "ta": "ரூ."}   # native check (ta: Palmera's Mapping sheet writes "Rs.")

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    # native check
    "si": ["ජනවාරි", "පෙබරවාරි", "මාර්තු", "අප්‍රේල්", "මැයි", "ජූනි", "ජූලි", "අගෝස්තු", "සැප්තැම්බර්",
           "ඔක්තෝබර්", "නොවැම්බර්", "දෙසැම්බර්"],
    # native check
    "ta": ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்",
           "அக்டோபர்", "நவம்பர்", "டிசம்பர்"],
}

# Palmera Mapping sheet, columns A (ta), B (si), C (en)
PALMERA_LABELS = {
    "Total number of meetings held": {"si": "පැවැත්වූ මුළු රැස්වීම් ගණන", "ta": "நடத்தப்பட்ட கூட்டங்களின் மொத்த எண்ணிக்கை"},
    "Number of SHG members": {"si": "SHG සාමාජිකයින් සංඛ්‍යාව", "ta": "SHG உறுப்பினர்களின் எண்ணிக்கை"},
    "Total attendance for the month": {"si": "මාසය සඳහා මුළු පැමිණීම", "ta": "மாதத்திற்கான மொத்த வருகை"},
    "Savings (Rs.)": {"si": "ඉතුරුම් (රු.)", "ta": "சேமிப்பு (Rs.)"},
    "Principal loan repayments (Rs.)": {"si": "මූලික ණය ආපසු ගෙවීම් (රු.)", "ta": "அசல் கடன் மீள் கொடுப்பனவுகள் (Rs.)"},
    "Interest repayment (Rs.)": {"si": "පොලී ආපසු ගෙවීම (රු.)", "ta": "வட்டி செலுத்தப்பட்டது (Rs.)"},
    "Loans distributed (Rs.)": {"si": "බෙදා හරින ලද ණය (රු.)", "ta": "வழங்கப்பட்ட கடன்கள் (Rs.)"},
    "Cash in Hand – at end of month (mother book) (Rs.)": {"si": "අතේ ඇති මුදල් - මාසය අවසානයේ (මව් පොත) (රු.)", "ta": "கையில் உள்ள பணம் – மாதத்தின் முடிவில் (தாய்ப் புத்தகம்) (Rs.)"},
}

# the numbered list a member confirms (summary key, English short name)
SUMMARY_ITEMS = [
    ("header.shg_name", "Group"),
    ("header.month_year", "Month"),
    ("Total number of meetings held", "Meetings held"),
    ("Total attendance for the month", "Total attendance"),
    ("Savings (Rs.)", "Savings"),
    ("Principal loan repayments (Rs.)", "Loan repayments"),
    ("Interest repayment (Rs.)", "Interest"),
    ("Loans distributed (Rs.)", "Loans given"),
    ("Cash in Hand – at end of month (mother book) (Rs.)", "Cash in hand (month end)"),
    # Item 10, not 3: the member count is written to the workbook and a misread one skews
    # every attendance rate. It goes last so "5 12000" (savings) keeps its number.
    ("Number of SHG members", "Members"),
]

HEADER_LABELS = {"header.shg_name": {"si": "කණ්ඩායම", "ta": "குழு"},
                 "header.month_year": {"si": "මාසය", "ta": "மாதம்"}}

TEXT: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- photos
    "ask_page2": {
        "en": "Thank you! Page 1 is clear. Please send a photo of page 2 now.",
        "si": "ස්තූතියි! 1 වන පිටුව පැහැදිලියි. කරුණාකර දැන් 2 වන පිටුවේ ඡායාරූපයක් එවන්න.",
        "ta": "நன்றி! பக்கம் 1 தெளிவாக உள்ளது. இப்போது பக்கம் 2 இன் புகைப்படத்தை அனுப்புங்கள்.",
    },
    "ask_page1": {
        "en": "Thank you! Please also send a photo of page 1 (the page with the weekly table).",
        "si": "ස්තූතියි! කරුණාකර 1 වන පිටුවේ (සතිපතා වගුව ඇති පිටුව) ඡායාරූපයත් එවන්න.",
        "ta": "நன்றி! தயவுசெய்து பக்கம் 1 இன் (வாராந்திர அட்டவணை உள்ள பக்கம்) புகைப்படத்தையும் அனுப்புங்கள்.",
    },
    "waiting_page2": {
        "en": "We have page 1 of your report. Please send a photo of page 2.",
        "si": "ඔබේ වාර්තාවේ 1 වන පිටුව අපට ලැබුණා. කරුණාකර 2 වන පිටුවේ ඡායාරූපයක් එවන්න.",  # native check
        "ta": "உங்கள் அறிக்கையின் பக்கம் 1 கிடைத்தது. தயவுசெய்து பக்கம் 2 இன் புகைப்படத்தை அனுப்புங்கள்.",  # native check
    },
    "reading": {
        "en": "We are reading your report now. Please wait a moment.",
        "si": "අපි දැන් ඔබේ වාර්තාව කියවමින් සිටිමු. කරුණාකර මොහොතක් රැඳී සිටින්න.",  # native check
        "ta": "உங்கள் அறிக்கையை இப்போது படிக்கிறோம். சற்று காத்திருங்கள்.",  # native check
    },
    "bad_image": {
        "en": "Sorry, I could not open this photo. Please take the photo again with the phone camera and send it as a photo.",
        "si": "කණගාටුයි, මට මෙම ඡායාරූපය විවෘත කළ නොහැකි වුණා. කරුණාකර දුරකථන කැමරාවෙන් නැවත ඡායාරූපයක් ගෙන එය ඡායාරූපයක් ලෙස එවන්න.",  # native check
        "ta": "மன்னிக்கவும், இந்தப் புகைப்படத்தைத் திறக்க முடியவில்லை. தொலைபேசி கேமராவில் மீண்டும் புகைப்படம் எடுத்து, புகைப்படமாக அனுப்புங்கள்.",  # native check
    },
    "send_again": {
        "en": "Sorry, we could not receive your photo. Please send it again.",
        "si": "කණගාටුයි, ඔබේ ඡායාරූපය අපට ලැබුණේ නැහැ. කරුණාකර එය නැවත එවන්න.",  # native check
        "ta": "மன்னிக்கவும், உங்கள் புகைப்படம் எங்களுக்குக் கிடைக்கவில்லை. தயவுசெய்து மீண்டும் அனுப்புங்கள்.",  # native check
    },
    # ---------------------------------------------------------------- reading + officer
    "checking": {
        "en": "Thank you, we have your report. A monitoring officer is checking a few numbers and we will send you a summary soon.",
        "si": "ස්තූතියි, ඔබේ වාර්තාව ලැබුණා. අධීක්ෂණ නිලධාරියෙක් ඉලක්කම් කිහිපයක් පරීක්ෂා කරමින් සිටී. ඉක්මනින් සාරාංශයක් එවන්නෙමු.",
        "ta": "நன்றி, உங்கள் அறிக்கை கிடைத்தது. கண்காணிப்பு அலுவலர் சில எண்களை சரிபார்க்கிறார். விரைவில் சுருக்கத்தை அனுப்புவோம்.",
    },
    "confirmed_pending": {   # she said OK, but the workbook couldn't be written yet
        "en": "Thank you for confirming. An officer will record your report shortly, then we will send you a receipt.",
        "si": "තහවුරු කළාට ස්තූතියි. නිලධාරියෙක් ඉක්මනින් ඔබේ වාර්තාව සටහන් කරනු ඇත. ඉන්පසු අපි ඔබට රිසිට්පතක් එවන්නෙමු.",  # native check
        "ta": "உறுதிப்படுத்தியதற்கு நன்றி. அலுவலர் விரைவில் உங்கள் அறிக்கையைப் பதிவு செய்வார். பிறகு உங்களுக்கு ரசீது அனுப்புவோம்.",  # native check
    },
    "officer_checking": {
        "en": "An officer is still checking your report. We will send you the summary soon. Thank you for waiting.",
        "si": "නිලධාරියෙක් තවමත් ඔබේ වාර්තාව පරීක්ෂා කරමින් සිටී. ඉක්මනින් සාරාංශය එවන්නෙමු. රැඳී සිටීමට ස්තූතියි.",  # native check
        "ta": "அலுவலர் இன்னும் உங்கள் அறிக்கையைச் சரிபார்க்கிறார். விரைவில் சுருக்கத்தை அனுப்புவோம். காத்திருந்தமைக்கு நன்றி.",  # native check
    },
    "extraction_failed": {
        "en": "Sorry, we could not read your report this time. An officer will look at it. You do not need to do anything now.",
        "si": "කණගාටුයි, මෙවර ඔබේ වාර්තාව කියවීමට අපට නොහැකි වුණා. නිලධාරියෙක් එය බලනු ඇත. ඔබට දැන් කිසිවක් කිරීමට අවශ්‍ය නැහැ.",  # native check
        "ta": "மன்னிக்கவும், இம்முறை உங்கள் அறிக்கையைப் படிக்க முடியவில்லை. அலுவலர் அதைப் பார்ப்பார். நீங்கள் இப்போது எதுவும் செய்ய வேண்டியதில்லை.",  # native check
    },
    "demo_unknown_photo": {
        "en": "This is a demo. It can only read the sample report photos, not this photo. Please send one of the sample photos.",
        "si": "මෙය නිරූපණයක් (demo) පමණයි. එයට කියවිය හැක්කේ නියැදි වාර්තා ඡායාරූප පමණයි, මෙම ඡායාරූපය නොවේ. කරුණාකර නියැදි ඡායාරූපයක් එවන්න.",  # native check
        "ta": "இது ஒரு டெமோ மட்டுமே. இது மாதிரி அறிக்கைப் புகைப்படங்களை மட்டுமே படிக்கும், இந்தப் புகைப்படத்தை அல்ல. தயவுசெய்து ஒரு மாதிரிப் புகைப்படத்தை அனுப்புங்கள்.",  # native check
    },
    "rejected": {
        "en": "Sorry, we could not use the photos you sent.{reason} Please take new photos of page 1 and page 2 and send them again.",
        "si": "කණගාටුයි, ඔබ එවූ ඡායාරූප අපට භාවිත කළ නොහැකි වුණා.{reason} කරුණාකර 1 සහ 2 පිටු වල අලුත් ඡායාරූප ගෙන නැවත එවන්න.",  # native check
        "ta": "மன்னிக்கவும், நீங்கள் அனுப்பிய புகைப்படங்களைப் பயன்படுத்த முடியவில்லை.{reason} தயவுசெய்து பக்கம் 1, பக்கம் 2 இரண்டையும் மீண்டும் புகைப்படம் எடுத்து அனுப்புங்கள்.",  # native check
    },
    # ---------------------------------------------------------------- summary + replies
    "summary_intro": {
        "en": "Here is what we read from your report. Please check it:",
        "si": "ඔබේ වාර්තාවෙන් අප කියවූ දේ මෙන්න. කරුණාකර පරීක්ෂා කරන්න:",
        "ta": "உங்கள் அறிக்கையிலிருந்து நாங்கள் படித்தது இதோ. தயவுசெய்து சரிபாருங்கள்:",
    },
    "summary_ask": {
        "en": "Reply OK if everything is correct.\nIf something is wrong, reply with the number and the right value, e.g. \"5 12000\".",
        "si": "සියල්ල නිවැරදි නම් OK ලෙස පිළිතුරු දෙන්න.\nයමක් වැරදි නම්, අංකය සහ නිවැරදි අගය එවන්න, උදා: \"5 12000\".",
        "ta": "எல்லாம் சரியாக இருந்தால் OK என பதிலளிக்கவும்.\nஏதாவது தவறாக இருந்தால், எண்ணையும் சரியான மதிப்பையும் அனுப்புங்கள், உதா: \"5 12000\".",
    },
    "correction_noted": {
        "en": "Thank you. We noted that item {n} should be {value}. An officer will check it against your form, then send you the summary again.",
        "si": "ස්තූතියි. අංක {n} අයිතමය {value} විය යුතු බව සටහන් කර ගත්තා. නිලධාරියෙක් එය ඔබේ පෝරමය සමඟ පරීක්ෂා කර, සාරාංශය නැවත එවනු ඇත.",  # native check
        "ta": "நன்றி. உருப்படி {n} {value} ஆக இருக்க வேண்டும் என்று குறித்துக்கொண்டோம். அலுவலர் அதை உங்கள் படிவத்துடன் சரிபார்த்து, சுருக்கத்தை மீண்டும் அனுப்புவார்.",  # native check
    },
    "correction_same": {
        "en": "Item {n} already says {value}. If everything is correct, reply OK.",
        "si": "අංක {n} අයිතමයේ දැනටමත් {value} ලෙස තිබෙනවා. සියල්ල නිවැරදි නම් OK ලෙස පිළිතුරු දෙන්න.",  # native check
        "ta": "உருப்படி {n} இல் ஏற்கனவே {value} என உள்ளது. எல்லாம் சரியாக இருந்தால் OK என பதிலளிக்கவும்.",  # native check
    },
    "not_understood": {
        "en": "Sorry, I did not understand. Reply OK if everything is correct. To fix a number, send the item number and the right amount, like this: 5 12000",
        "si": "කණගාටුයි, මට තේරුණේ නැහැ. සියල්ල නිවැරදි නම් OK ලෙස පිළිතුරු දෙන්න. ඉලක්කමක් වැරදි නම්, අයිතමයේ අංකය සහ නිවැරදි මුදල මෙලෙස එවන්න: 5 12000",  # native check
        "ta": "மன்னிக்கவும், புரியவில்லை. எல்லாம் சரியாக இருந்தால் OK என பதிலளிக்கவும். ஒரு எண்ணைத் திருத்த, உருப்படி எண்ணையும் சரியான தொகையையும் இப்படி அனுப்புங்கள்: 5 12000",  # native check
    },
    "not_understood_value": {
        "en": "Sorry, I could not read the value for item {n}. Please send one item number and one value, like this: 5 12000",
        "si": "කණගාටුයි, අංක {n} අයිතමයේ අගය මට කියවිය නොහැකි වුණා. කරුණාකර එක් අයිතම අංකයක් සහ එක් අගයක් මෙලෙස එවන්න: 5 12000",  # native check
        "ta": "மன்னிக்கவும், உருப்படி {n} இன் மதிப்பைப் படிக்க முடியவில்லை. ஒரு உருப்படி எண்ணையும் ஒரு மதிப்பையும் இப்படி அனுப்புங்கள்: 5 12000",  # native check
    },
    "receipt": {
        "en": "✅ Your {month} report for {group} is recorded.\nSavings this month: {savings}\nLoan repayments: {repay}\nCash in hand at month end: {cash}{progress}\nThank you!",
        "si": "✅ {group} කණ්ඩායමේ {month} වාර්තාව සටහන් කළා.\nමෙම මාසයේ ඉතුරුම්: {savings}\nණය ආපසු ගෙවීම්: {repay}\nමාසය අවසානයේ අතේ ඇති මුදල්: {cash}{progress}\nස්තූතියි!",  # native check
        "ta": "✅ {group} குழுவின் {month} அறிக்கை பதிவு செய்யப்பட்டது.\nஇம்மாத சேமிப்பு: {savings}\nகடன் மீள் கொடுப்பனவு: {repay}\nமாத இறுதியில் கையிலுள்ள பணம்: {cash}{progress}\nநன்றி!",  # native check
    },
    "receipt_progress": {
        "en": "Your group's total savings so far: {total}.",
        "si": "ඔබේ කණ්ඩායමේ මේ දක්වා මුළු ඉතුරුම්: {total}.",  # native check
        "ta": "உங்கள் குழுவின் இதுவரையான மொத்த சேமிப்பு: {total}.",  # native check
    },
    "already_recorded": {
        "en": "Your {month} report for {group} is already recorded. Thank you!",
        "si": "{group} කණ්ඩායමේ {month} වාර්තාව දැනටමත් සටහන් කර ඇත. ස්තූතියි!",  # native check
        "ta": "{group} குழுவின் {month} அறிக்கை ஏற்கனவே பதிவு செய்யப்பட்டுள்ளது. நன்றி!",  # native check
    },
    "no_report": {
        "en": "Please send a photo of page 1 of your SHG monthly report, then a photo of page 2.",
        "si": "කරුණාකර ඔබේ SHG මාසික වාර්තාවේ 1 වන පිටුවේ ඡායාරූපයක් එවන්න. ඉන්පසු 2 වන පිටුවේ ඡායාරූපයක් එවන්න.",  # native check
        "ta": "தயவுசெய்து உங்கள் SHG மாதாந்திர அறிக்கையின் பக்கம் 1 இன் புகைப்படத்தை அனுப்புங்கள். பிறகு பக்கம் 2 இன் புகைப்படத்தை அனுப்புங்கள்.",  # native check
    },
    "choose_language": {
        "en": "For Sinhala, reply සිංහල. For Tamil, reply தமிழ்.",
        "si": "For Sinhala, reply සිංහල. For Tamil, reply தமிழ்.",
        "ta": "For Sinhala, reply සිංහල. For Tamil, reply தமிழ்.",
    },
    "lang_set": {
        "en": "OK. We will reply in English.",
        "si": "හරි. අපි සිංහලෙන් පිළිතුරු දෙන්නෙමු.",  # native check
        "ta": "சரி. நாங்கள் தமிழில் பதிலளிப்போம்.",  # native check
    },
    "unsupported": {
        "en": "Sorry, I can only read photos and short text messages. Please send a photo of each page of your report.",
        "si": "කණගාටුයි, මට කියවිය හැක්කේ ඡායාරූප සහ කෙටි පණිවිඩ පමණයි. කරුණාකර ඔබේ වාර්තාවේ සෑම පිටුවකම ඡායාරූපයක් එවන්න.",  # native check
        "ta": "மன்னிக்கவும், புகைப்படங்களையும் சிறு செய்திகளையும் மட்டுமே படிக்க முடியும். உங்கள் அறிக்கையின் ஒவ்வொரு பக்கத்தையும் புகைப்படமாக அனுப்புங்கள்.",  # native check
    },
    "error_fallback": {
        "en": "Sorry, something went wrong on our side. An officer will look at it.",
        "si": "කණගාටුයි, අපේ පැත්තෙන් දෝෂයක් සිදු වුණා. නිලධාරියෙක් එය බලනු ඇත.",  # native check
        "ta": "மன்னிக்கவும், எங்கள் பக்கத்தில் ஒரு பிழை ஏற்பட்டது. அலுவலர் அதைப் பார்ப்பார்.",  # native check
    },
    # ---------------------------------------------------------------- consent
    "privacy": {
        "en": "Palmera uses these photos only to record your group's monthly report. Reply STOP to opt out.",
        "si": "Palmera මෙම ඡායාරූප භාවිත කරන්නේ ඔබේ කණ්ඩායමේ මාසික වාර්තාව සටහන් කිරීමට පමණයි. ඉවත් වීමට STOP ලෙස පිළිතුරු දෙන්න.",  # native check
        "ta": "Palmera இந்தப் புகைப்படங்களை உங்கள் குழுவின் மாதாந்திர அறிக்கையைப் பதிவு செய்ய மட்டுமே பயன்படுத்துகிறது. விலக STOP என பதிலளிக்கவும்.",  # native check
    },
    "stopped": {
        "en": "You have opted out. We will not use your photos, and we will not message you again. To send a report later, just send a photo.",
        "si": "ඔබ ඉවත් වුණා. අපි ඔබේ ඡායාරූප භාවිත නොකරමු. ඔබට නැවත පණිවිඩ නොඑවමු. පසුව වාර්තාවක් එවීමට, ඡායාරූපයක් එවන්න.",  # native check
        "ta": "நீங்கள் விலகிவிட்டீர்கள். உங்கள் புகைப்படங்களைப் பயன்படுத்த மாட்டோம். மீண்டும் செய்தி அனுப்ப மாட்டோம். பின்னர் அறிக்கை அனுப்ப, ஒரு புகைப்படத்தை அனுப்புங்கள்.",  # native check
    },
}

# Why an officer rejected a report, in simple words for the member. Codes are what the
# dashboard sends; anything else is treated as "other" (the officer's own note is logged,
# never forwarded: it is in English and may be blunt).
REJECT_REASONS: dict[str, dict[str, str]] = {
    "unclear": {
        "en": "The photos are not clear enough to read.",
        "si": "ඡායාරූප කියවීමට තරම් පැහැදිලි නැහැ.",  # native check
        "ta": "புகைப்படங்கள் படிக்கும் அளவுக்குத் தெளிவாக இல்லை.",  # native check
    },
    "missing_page": {
        "en": "A page is missing.",
        "si": "පිටුවක් අඩුයි.",  # native check
        "ta": "ஒரு பக்கம் இல்லை.",  # native check
    },
    "wrong_form": {
        "en": "This is not the SHG monthly report form.",
        "si": "මෙය SHG මාසික වාර්තා පෝරමය නොවේ.",  # native check
        "ta": "இது SHG மாதாந்திர அறிக்கைப் படிவம் அல்ல.",  # native check
    },
    "wrong_group": {
        "en": "The group name or the month on the form is not right.",
        "si": "පෝරමයේ කණ්ඩායමේ නම හෝ මාසය නිවැරදි නැහැ.",  # native check
        "ta": "படிவத்தில் உள்ள குழுவின் பெயர் அல்லது மாதம் சரியாக இல்லை.",  # native check
    },
    "incomplete": {
        "en": "Some parts of the form are empty.",
        "si": "පෝරමයේ සමහර කොටස් හිස්ව තිබෙනවා.",  # native check
        "ta": "படிவத்தின் சில பகுதிகள் நிரப்பப்படவில்லை.",  # native check
    },
    "other": {"en": "", "si": "", "ta": ""},
}


# --------------------------------------------------------------------------- replies
class Reply(str):
    """A bot message: the text in the member's language, plus `.en`, the same message in
    English (None when the member's language is English). `.mid` is the message id shared by
    the submission log and the conversation log once it is recorded, so the WhatsApp
    delivery result can be written back to both."""
    en: Optional[str]
    mid: Optional[str] = None

    def __new__(cls, text: str, en: Optional[str] = None, mid: Optional[str] = None):
        obj = super().__new__(cls, text)
        obj.en = en
        obj.mid = mid
        return obj

    def then(self, other: "Reply") -> "Reply":
        """This message followed by another one in the same bubble (one message, one id)."""
        en = None
        other_en = getattr(other, "en", None)
        if self.en or other_en:
            en = f"{self.en or str(self)}\n\n{other_en or str(other)}"
        return Reply(f"{self}\n\n{other}", en, self.mid or getattr(other, "mid", None))


def _lang(lang: Optional[str]) -> str:
    return lang if lang in LANGS else "en"


def _resolve(v: Any, lang: str) -> Any:
    """Arguments can be given per language as {'en': …, 'si': …, 'ta': …}."""
    if isinstance(v, dict):
        return v.get(lang, v.get("en", ""))
    return v


def t(key: str, lang: str, **kw: Any) -> str:
    lang = _lang(lang)
    s = TEXT[key].get(lang) or TEXT[key]["en"]
    return s.format(**{k: _resolve(v, lang) for k, v in kw.items()})


def msg(key: str, lang: str, **kw: Any) -> Reply:
    lang = _lang(lang)
    return Reply(t(key, lang, **kw), t(key, "en", **kw) if lang != "en" else None)


def per_lang(fn) -> dict[str, Any]:
    """{lang: fn(lang)} for every language, to pass as a message argument."""
    return {lang: fn(lang) for lang in LANGS}


# --------------------------------------------------------------------------- formatting
def number(v: Any) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return str(v)


def money(v: Any, lang: str) -> str:
    """'Rs. 11,400' in the member's currency style; '—' when the figure is missing."""
    if v is None or v == "":
        return "—"
    return f"{CURRENCY[_lang(lang)]} {number(v)}"


def month_name(ym: Optional[str], lang: str) -> str:
    """'2026-10' -> 'October 2026' / 'ඔක්තෝබර් 2026' / 'அக்டோபர் 2026'."""
    if not ym:
        return "—"
    m = re.fullmatch(r"(\d{4})-(\d{2})", str(ym))
    if not m or not 1 <= int(m[2]) <= 12:
        return str(ym)
    return f"{MONTHS[_lang(lang)][int(m[2]) - 1]} {m[1]}"


def is_money_item(key: str) -> bool:
    return key.endswith("(Rs.)")


def display_value(key: str, v: Any, lang: str) -> str:
    """How one summary item's value is shown to the member."""
    if key == "header.month_year":
        return month_name(v, lang)
    return number(v)


def _label(label: str, short: str, lang: str) -> str:
    lang = _lang(lang)
    if lang in ("si", "ta"):
        if label in PALMERA_LABELS:
            return PALMERA_LABELS[label][lang].replace("(Rs.)", f"({CURRENCY[lang]})")
        if label in HEADER_LABELS:
            return HEADER_LABELS[label][lang]
    return f"{short} ({CURRENCY['en']})" if is_money_item(label) else short


# --------------------------------------------------------------------------- summary + receipt
def summary_values(rec: FormRecord, tpl: Template) -> list[tuple[str, str, Any]]:
    """[(key, English short name, value)] for the numbered summary, exactly as it would be
    written (no pending member corrections)."""
    monthly = to_monthly(rec, tpl, include_optional=False)
    return [(key, short, rec.get(key) if key.startswith("header.") else monthly.get(key))
            for key, short in SUMMARY_ITEMS]


def _summary_text(items: list[tuple[str, str, Any]], lang: str) -> str:
    lines = [t("summary_intro", lang), ""]
    for i, (key, short, v) in enumerate(items, 1):
        lines.append(f"{i}. {_label(key, short, lang)}: {display_value(key, v, lang)}")
    lines += ["", t("summary_ask", lang)]
    return "\n".join(lines)


def summary_items(rec: FormRecord, tpl: Template, lang: str) -> list[dict[str, Any]]:
    """The numbered items of her WhatsApp summary, for the dashboard (what she confirms).
    `monthly_label` is the workbook row the item is (None for the group name and month)."""
    lang = _lang(lang)
    monthly = {r["label"] for r in tpl.workbook["monthly_rows"]}
    return [{"n": i, "key": key, "label_en": _label(key, short, "en"), "label": _label(key, short, lang),
             "value": v, "display": display_value(key, v, lang), "display_en": display_value(key, v, "en"),
             "monthly_label": key if key in monthly else None}
            for i, (key, short, v) in enumerate(summary_values(rec, tpl), 1)]


def member_summary(rec: FormRecord, tpl: Template, lang: str) -> Reply:
    lang = _lang(lang)
    items = summary_values(rec, tpl)
    return Reply(_summary_text(items, lang), _summary_text(items, "en") if lang != "en" else None)


def receipt(lang: str, *, month: Optional[str], group: Any, savings: Any, repay: Any, cash: Any,
            savings_to_date: Optional[float] = None) -> Reply:
    progress = per_lang(lambda l: "\n" + t("receipt_progress", l, total=money(savings_to_date, l))
                        if savings_to_date is not None else "")
    return msg("receipt", lang, month=per_lang(lambda l: month_name(month, l)), group=group or "—",
               savings=per_lang(lambda l: money(savings, l)), repay=per_lang(lambda l: money(repay, l)),
               cash=per_lang(lambda l: money(cash, l)), progress=progress)


def rejected(lang: str, reason_code: str) -> Reply:
    reasons = REJECT_REASONS.get(reason_code) or REJECT_REASONS["other"]
    return msg("rejected", lang, reason=per_lang(lambda l: (" " + reasons[l]) if reasons[l] else ""))


# --------------------------------------------------------------------------- reading replies
_LETTERS = r"[a-z0-9඀-෿஀-௿‌‍]+|👍|✅|👌"
YES = {"ok", "okay", "okey", "okk", "oky", "yes", "y", "correct", "right", "done",
       "ඔව්", "ඔව", "හරි", "ஆம்", "சரி", "ஓகே", "ஓக்கே", "👍", "✅", "👌"}
_POLITE = {"thanks", "thank", "you", "thx", "all", "everything", "is", "its", "fine", "good", "very", "sure",
           "madam", "sir", "miss", "ස්තූතියි", "ස්තුතියි", "நன்றி"}
STOP_WORDS = {"stop", "unsubscribe", "opt out", "optout", "නවත්වන්න", "නවතන්න", "நிறுத்து", "நிறுத்தவும்",
              "நிறுத்துங்கள்"}
LANG_WORDS = {"english": "en", "ඉංග්‍රීසි": "en", "ஆங்கிலம்": "en",
              "sinhala": "si", "sinhalese": "si", "සිංහල": "si", "சிங்களம்": "si",
              "tamil": "ta", "දෙමළ": "ta", "தமிழ்": "ta"}

_DIGITS = str.maketrans({**{chr(0x0DE6 + i): str(i) for i in range(10)},      # Sinhala Lith digits
                         **{chr(0x0BE6 + i): str(i) for i in range(10)}})     # Tamil digits


def ascii_digits(s: str) -> str:
    """Sinhala/Tamil/full-width digits -> 0-9."""
    return unicodedata.normalize("NFKC", s).translate(_DIGITS)


def _tokens(text: str) -> list[str]:
    return re.findall(_LETTERS, unicodedata.normalize("NFC", text).lower())


def _plain(text: str) -> str:
    return " ".join(_tokens(text))


def is_confirm(text: str) -> bool:
    toks = _tokens(text)
    return bool(toks) and any(w in YES for w in toks) and all(w in YES or w in _POLITE for w in toks)


def is_stop(text: str) -> bool:
    return _plain(text) in STOP_WORDS


def language_keyword(text: str) -> Optional[str]:
    return LANG_WORDS.get(_plain(text))


def script_lang(text: str) -> Optional[str]:
    """'si' or 'ta' if the member writes in that script."""
    si = sum(1 for c in text if "඀" <= c <= "෿")
    ta = sum(1 for c in text if "஀" <= c <= "௿")
    if si > ta:
        return "si"
    if ta > si:
        return "ta"
    return None


_ITEM = re.compile(r"(?:no\.?|item|#)?\s*(\d{1,3})\s*(?:[.):=\-–—]+\s*|\s+)(\S.*)", re.I | re.S)


def parse_member_reply(text: str) -> tuple[str, Any]:
    """('confirm', None) | ('correct', (item_no, raw_value)) | ('unknown', None).
    The value is checked later, by the item's type (parse_amount for numbers)."""
    s = ascii_digits(text or "").strip()
    if is_confirm(s):
        return "confirm", None
    m = _ITEM.fullmatch(s)
    if m:
        n = int(m[1])
        if 1 <= n <= len(SUMMARY_ITEMS):
            return "correct", (n, m[2].strip())
    return "unknown", None


_CURRENCY_WORDS = r"(?:rs\.?|lkr|රු\.?|රුපියල්|ரூ\.?|ரூபாய்)"
_GROUPED = re.compile(r"\d{1,3}(?:,\d{2,3})*,\d{3}(?:\.\d{1,2})?")
_PLAIN = re.compile(r"\d+(?:\.\d{1,2})?")


def parse_amount(raw: str, integer: bool = False) -> float | int:
    """'12000', '12,000', 'Rs.12000/=', '12,000/-', 'රු. 12000', '௧௨௦௦௦' -> 12000.
    Two numbers ('300 310') or anything unclear raises ValueError: better to ask again
    than to guess."""
    s = ascii_digits(str(raw)).strip().lower()
    prev = None
    while s != prev:                                   # peel currency words and '/=', '/-' endings
        prev = s
        s = re.sub(rf"^{_CURRENCY_WORDS}\s*", "", s)
        s = re.sub(rf"\s*(?:{_CURRENCY_WORDS}|/=|/-|=/-|=-|/|=|-)$", "", s).strip()
    if not (_GROUPED.fullmatch(s) or _PLAIN.fullmatch(s)):
        raise ValueError(f"not one amount: {raw!r}")
    v = float(s.replace(",", ""))
    if v > 1e8:
        raise ValueError(f"too large: {raw!r}")
    if integer:
        if not v.is_integer():
            raise ValueError(f"not a whole number: {raw!r}")
        return int(v)
    return int(v) if v.is_integer() else v
