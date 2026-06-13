import os
import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

# নতুন রাউটার ইনিশিয়েট করা (যা মূল কোডে হাত না দিয়েই কাজ করবে)
gateway_router = APIRouter(prefix="/gateway", tags=["Network Gateway"])

# কিছু গ্লোবাল ফ্রি পাবলিক ডিএনএস এবং প্রক্সি গেটওয়ে লিস্ট (যা সহজে ব্লক হয় না)
FALLBACK_GATEWAYS = [
    "https://workers.cloudflare.com",
    "https://vercel.live",
    "https://pages.dev"
]

@gateway_router.get("/dns-check")
async def check_network_status(request: Request):
    """
    ইউজারের নেটওয়ার্ক কানেকশন টেস্ট করার জন্য এন্ডপয়েন্ট।
    ইউজার যদি সরাসরি কানেক্ট করতে না পারে, তবে সে এই গেটওয়ের সাহায্য নেবে।
    """
    client_host = request.client.host
    return {
        "status": "online",
        "message": "Gateway Connection Successful",
        "client_ip": client_host,
        "suggested_gateways": FALLBACK_GATEWAYS
    }

@gateway_router.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def reverse_proxy_gateway(request: Request, path: str):
    """
    একটি ইন্টারনাল রিভার্স প্রক্সি যা যেকোনো ব্লকড নেটওয়ার্কের ট্রাফিককে 
    অন্য একটি সচল সার্ভারের মাধ্যমে আপনার ব্যাকএন্ডে টানেল করে নিয়ে আসে।
    """
    # আপনার লোকাল হোস্ট বা মেইন সার্ভার ইউআরএল (যেমন: Render বা VPS এর লোকাল পোর্ট)
    target_url = f"http://127.0.0.1:8000/{path}" 
    
    # রিকোয়েস্টের হেডার ও ডাটা কপি করা
    headers = dict(request.headers)
    # Host হেডারটি পরিবর্তন করা যাতে লোকাল হোস্ট কনফ্লিক্ট না করে
    headers.pop("host", None)
    
    async with httpx.AsyncClient() as client:
        try:
            # মেথড অনুযায়ী রিকোয়েস্ট পাঠানো
            content = await request.body()
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                params=request.query_params,
                content=content,
                timeout=10.0
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except Exception as e:
            return JSONResponse(
                status_code=502,
                content={"error": "Gateway Timeout", "details": str(e)}
            )
