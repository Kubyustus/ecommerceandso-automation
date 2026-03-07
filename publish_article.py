import os
import json
import random
import requests
import base64
from io import BytesIO
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# 1. LOAD SECRETS FROM GITHUB ACTIONS
# ==========================================
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")
SHOP_DOMAIN = os.environ.get("SHOP_DOMAIN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
AUTHOR_NAME = os.environ.get("AUTHOR_NAME", "Neriad Hakak")
BLOG_ID_REC = os.environ.get("BLOG_ID_RECOMMENDATIONS")
BLOG_ID_ECOM = os.environ.get("BLOG_ID_ECOMMERCE")

client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================================
# 2. LOAD FILES (QUEUE & FEATURED POSTS)
# ==========================================
print("Loading data files...")
with open("pending_posts.json", "r") as f:
    pending_posts = json.load(f)

with open("featured_posts.json", "r") as f:
    featured_posts = json.load(f)

if not pending_posts:
    print("Queue is empty! Time to run the Phase 3 Generator again.")
    exit(0)

# Pop the top post from the queue
current_post = pending_posts.pop(0)
target_blog_name = current_post["target_blog"]
blog_id = BLOG_ID_REC if target_blog_name == "Shopify Recommendations" else BLOG_ID_ECOM
title = current_post["title"]
short_name = current_post["short_name_for_image"]
topic_summary = current_post["topic_summary"]

print(f"🎯 Target Blog: {target_blog_name}")
print(f"📝 Writing Article: {title}")

# ==========================================
# 3. GENERATE GEO-OPTIMIZED CONTENT
# ==========================================
print("Prompting GPT-4o for content...")
prompt = f"""
You are an expert B2B eCommerce writer. Write a GEO-optimized blog post based on this title: "{title}".
Topic Context: {topic_summary}

STRICT GEO/SEO RULES:
1. Do not include the H1 title in the body (Shopify does this automatically).
2. Start immediately with a "Bottom Line Up Front" (BLUF) paragraph (40-80 words directly answering the title).
3. Use semantic HTML (<h2>, <h3>, <p>, <ul>, <strong>). Format subheadings as questions where relevant.
4. Add a short FAQ widget at the very bottom using <h3> tags for the questions.
5. Keep the tone authoritative, professional, and B2B-focused.

Output strictly in JSON format with these keys:
"body_html" (the full HTML article),
"meta_description" (a 150-character SEO description),
"tags" (a comma-separated string of 3-5 SEO tags).
"""

response = client.chat.completions.create(
    model="gpt-4o",
    response_format={ "type": "json_object" },
    messages=[{"role": "user", "content": prompt}]
)
article_data = json.loads(response.choices[0].message.content)
body_html = article_data["body_html"]

# ==========================================
# 4. INJECT INTERNAL LINKS (RULE 3)
# ==========================================
print("Injecting internal links...")
# Pick 2 random featured posts
selected_links = random.sample(featured_posts, 2)
internal_linking_html = f"""
<hr style="border-top: 2px solid #0073e6; margin-top: 40px; margin-bottom: 20px;">
<h3>More eCommerce Strategies You Might Like:</h3>
<ul>
  <li><strong><a href="{selected_links[0]['url']}" target="_blank">{selected_links[0]['title']}</a></strong>: {selected_links[0]['description']}</li>
  <li><strong><a href="{selected_links[1]['url']}" target="_blank">{selected_links[1]['title']}</a></strong>: {selected_links[1]['description']}</li>
</ul>
<br>
"""
# Attach links just above the FAQ if possible, or at the very bottom
if "<h3>FAQ" in body_html or "<h3>Frequently Asked Questions" in body_html:
    body_html = body_html.replace("<h3>FAQ", internal_linking_html + "<h3>FAQ")
else:
    body_html += internal_linking_html

# ==========================================
# 5. GENERATE BRAND CARD IMAGE
# ==========================================
print("Generating Brand Card...")
def generate_branded_image(text):
    width, height = 1024, 1024
    image = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(image)

    for x in range(width):
        r = int(0 + (0 - 0) * x / width)
        g = int(115 + (230 - 115) * x / width)
        b = int(230 + (115 - 230) * x / width)
        draw.line([(x, 0), (x, height)], fill=(r, g, b))

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 100)
    except:
        font = ImageFont.load_default()

    # Simple text wrap and center
    words = text.upper().split(' ')
    lines, current_line = [], ""
    for word in words:
        if draw.textbbox((0,0), current_line + word, font=font)[2] <= 900:
            current_line += word + " "
        else:
            lines.append(current_line.strip())
            current_line = word + " "
    lines.append(current_line.strip())

    total_h = sum(draw.textbbox((0,0), l, font=font)[3] for l in lines)
    y = (height - total_h) / 2
    for line in lines:
        lw = draw.textbbox((0,0), line, font=font)[2]
        draw.text(((width - lw)/2, y), line, font=font, fill="white")
        y += draw.textbbox((0,0), line, font=font)[3]

    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

base64_img = generate_branded_image(short_name)

# ==========================================
# 6. PUBLISH TO SHOPIFY
# ==========================================
print("Publishing to Shopify...")
url = f"https://{SHOP_DOMAIN}/admin/api/2024-01/blogs/{blog_id}/articles.json"
headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
payload = {
    "article": {
        "title": title,
        "author": AUTHOR_NAME,
        "body_html": body_html,
        "summary_html": article_data["meta_description"],
        "tags": article_data["tags"],
        "published": True,
        "image": {"attachment": base64_img}
    }
}

res = requests.post(url, headers=headers, json=payload)
if res.status_code == 201:
    print(f"✅ Success! Article Published.")
    # ONLY update the JSON file if Shopify successfully published it
    with open("pending_posts.json", "w") as f:
        json.dump(pending_posts, f, indent=2)
else:
    print(f"❌ Error publishing to Shopify: {res.text}")
    exit(1) # Crash the script so GitHub knows it failed and doesn't delete the post
