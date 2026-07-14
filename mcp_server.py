import sys
import json
import asyncio
from database.config import AsyncSessionLocal
from services.product_service import ProductService
from services.order_service import OrderService
from services.payment_service import PaymentService
from services.alatpay_service import BadRequestError
from schemas.order import OrderCreate, OrderItemCreate

TOOLS = [
    {
        "name": "search_products",
        "description": "Search for available products in the store's inventory and get their prices and stock availability.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_id": {
                    "type": "string",
                    "description": "The unique ID of the business."
                },
                "query": {
                    "type": "string",
                    "description": "Optional search term to filter products by name or description."
                }
            },
            "required": ["business_id"]
        }
    },
    {
        "name": "place_order",
        "description": "Place an order for products for the store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_id": {
                    "type": "string",
                    "description": "The unique ID of the business."
                },
                "customer_name": {
                    "type": "string",
                    "description": "Optional name of the customer placing the order."
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "integer"},
                            "quantity": {"type": "integer"}
                        },
                        "required": ["product_id", "quantity"]
                    },
                    "description": "List of items to order."
                }
            },
            "required": ["business_id", "items"]
        }
    },
    {
        "name": "create_payment_virtual_account",
        "description": "Generate a virtual bank account via ALATPay for the customer to transfer payment for an order.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "The integer ID of the order."
                }
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "verify_payment_status",
        "description": "Verify the status of a payment using the payment reference.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "The unique payment reference string."
                }
            },
            "required": ["reference"]
        }
    }
]

async def execute_tool(name: str, arguments: dict) -> dict:
    async with AsyncSessionLocal() as db:
        if name == "search_products":
            business_id = arguments.get("business_id")
            query = arguments.get("query", "")
            prod_service = ProductService(db)
            products = await prod_service.get_available_products(business_id=business_id)
            if query:
                q = query.lower()
                products = [p for p in products if q in p.name.lower() or (p.description and q in p.description.lower())]

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "products": [
                                {
                                    "product_id": p.id,
                                    "name": p.name,
                                    "description": p.description,
                                    "price": p.price,
                                    "stock_quantity": p.stock_quantity
                                } for p in products
                            ]
                        }, indent=2)
                    }
                ]
            }

        elif name == "place_order":
            business_id = arguments.get("business_id")
            customer_name = arguments.get("customer_name", "Customer")
            items = arguments.get("items", [])

            order_items = [
                OrderItemCreate(product_id=int(item["product_id"]), quantity=int(item["quantity"]))
                for item in items
            ]
            order_data = OrderCreate(
                business_id=business_id,
                customer_name=customer_name,
                items=order_items
            )
            order_service = OrderService(db)
            try:
                order = await order_service.create_order(order_data)
                result = {
                    "status": "success",
                    "order_id": order.id,
                    "total_amount": order.total_amount,
                    "order_status": order.status,
                    "message": f"Order {order.id} placed successfully. Total amount is NGN {order.total_amount}."
                }
            except ValueError as e:
                result = {"status": "error", "message": str(e)}
            except Exception as e:
                result = {"status": "error", "message": f"Failed to place order: {str(e)}"}

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2)
                    }
                ]
            }

        elif name == "create_payment_virtual_account":
            order_id = int(arguments.get("order_id"))
            order_service = OrderService(db)
            order = await order_service.get_order(order_id)
            if not order:
                result = {"status": "error", "message": f"Order with ID {order_id} not found."}
            else:
                payment_service = PaymentService(db)
                payment = await payment_service.create_payment(order_id, order.total_amount)
                try:
                    if payment.virtual_account:
                        account_data = {
                            "account_number": payment.virtual_account.account_number,
                            "account_name": payment.virtual_account.account_name,
                            "bank_name": payment.virtual_account.bank_name,
                            "expiry_minutes": 60
                        }
                    else:
                        account_data = await payment_service.generate_payment_virtual_account(
                            payment.id,
                            order.customer_name or "Customer"
                        )
                    result = {
                        "status": "success",
                        "payment_reference": payment.reference,
                        "account_number": account_data["account_number"],
                        "account_name": account_data["account_name"],
                        "bank_name": account_data["bank_name"],
                        "amount": payment.amount,
                        "currency": "NGN"
                    }
                except BadRequestError:
                    result = {"status": "error", "message": "Invalid request to generate virtual account"}
                except Exception as e:
                    result = {"status": "error", "message": f"Failed to generate virtual account: {str(e)}"}

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2)
                    }
                ]
            }

        elif name == "verify_payment_status":
            reference = arguments.get("reference")
            payment_service = PaymentService(db)
            try:
                payment = await payment_service.verify_and_update_payment(reference)
                if not payment:
                    result = {"status": "error", "message": f"Payment with reference {reference} not found."}
                else:
                    result = {
                        "status": "success",
                        "payment_reference": payment.reference,
                        "payment_status": payment.status,
                        "order_id": payment.order_id,
                        "amount": payment.amount
                    }
            except Exception as e:
                result = {"status": "error", "message": f"Failed to verify payment: {str(e)}"}

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2)
                    }
                ]
            }

        else:
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": f"Tool {name} not found"
                    }
                ]
            }


async def main():
    sys.stdout.reconfigure(line_buffering=True)

    def send_response(response_dict):
        sys.stdout.write(json.dumps(response_dict) + "\n")
        sys.stdout.flush()

    def send_error(id_, code, message):
        send_response({
            "jsonrpc": "2.0",
            "error": {
                "code": code,
                "message": message
            },
            "id": id_
        })

    while True:
        try:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                send_error(None, -32700, "Parse error")
                continue

            if not isinstance(msg, dict):
                send_error(None, -32600, "Invalid Request")
                continue

            id_ = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "paymate-mcp-server",
                            "version": "1.0.0"
                        }
                    },
                    "id": id_
                })
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "result": {
                        "tools": TOOLS
                    },
                    "id": id_
                })
            elif method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments", {})
                try:
                    result = await execute_tool(name, arguments)
                    send_response({
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": id_
                    })
                except Exception as e:
                    send_error(id_, -32603, f"Internal error during tool call: {str(e)}")
            else:
                if id_ is not None:
                    send_error(id_, -32601, f"Method not found: {method}")
        except Exception as e:
            sys.stderr.write(f"Error in main loop: {str(e)}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    asyncio.run(main())
