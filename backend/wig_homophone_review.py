"""Optional CPU phonetic candidates; never alter source evidence or approve identity."""
import re
from wig_catalog_names import hairstyle_name


def retrieve(cues, products, *, converter=None):
    if converter is None:
        from pypinyin import lazy_pinyin
        converter=lazy_pinyin
    names={}
    for product in products:
        name=hairstyle_name(product.get('product_name'))
        if name:names.setdefault(name, []).append(product['id'])
    aliases=[]
    for name,ids in names.items():
        for alias in re.split('[&＆]',name):
            # Short/generic syllables produce too many unrelated matches.
            if len(alias)>=3 and re.fullmatch(r'[\u4e00-\u9fff]+',alias):
                aliases.append((alias,tuple(converter(alias)),name,ids))
    hits=[]
    for cue in cues:
        text=cue['text']
        # Do not join separated phrases or punctuation into invented names.
        for match in re.finditer(r'[\u4e00-\u9fff]+',text):
            phrase=match.group();syllables=tuple(converter(phrase))
            if len(syllables)!=len(phrase):continue
            for alias,wanted,name,ids in aliases:
                for i in range(len(phrase)-len(alias)+1):
                    observed=phrase[i:i+len(alias)]
                    if observed!=alias and syllables[i:i+len(alias)]==wanted:
                        hits.append({'start_sec':cue['start_sec'],'end_sec':cue['end_sec'],
                                     'original_text':text,'observed_text':observed,'candidate_alias':alias,
                                     'hairstyle_name':name,'catalogue_ids':ids,
                                     'evidence':'same_toneless_pinyin_not_verified_audio',
                                     'current_assertion':False,'visual_verified':False,'sku_verified':False,
                                     'review_required':True})
    return hits

