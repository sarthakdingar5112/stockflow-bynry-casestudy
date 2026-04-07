from flask import request, jsonify
from sqlalchemy.exc import IntegrityError
import logging

# FIX #7: Correct HTTP method return codes documented at top
# FIX #6: In production, add @login_required or @jwt_required decorator here


@app.route('/api/products', methods=['POST'])
def create_product():
    """
    Creates a new product and its initial inventory record in a single atomic transaction.

    Required fields: name, sku, warehouse_id, initial_quantity
    Optional fields: price (defaults to 0)
    """

    # FIX #8: Use get_json() — safe against wrong Content-Type headers
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    # FIX #2: Validate all required fields upfront; return 400 with clear message
    required_fields = ['name', 'sku', 'warehouse_id', 'initial_quantity']
    missing = [f for f in required_fields if f not in data or data[f] is None]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    # FIX #5: Validate and sanitize price
    try:
        price = float(data.get('price', 0))
        if price < 0:
            raise ValueError("Price cannot be negative")
    except (ValueError, TypeError):
        return jsonify({"error": "price must be a non-negative number"}), 400

    # FIX #5: Validate initial_quantity
    try:
        initial_quantity = int(data['initial_quantity'])
        if initial_quantity < 0:
            raise ValueError("Quantity cannot be negative")
    except (ValueError, TypeError):
        return jsonify({"error": "initial_quantity must be a non-negative integer"}), 400

    try:
        # FIX #4: warehouse_id removed from Product model.
        #         A product can exist in many warehouses; that relationship
        #         is tracked in the Inventory table.
        product = Product(
            name=data['name'].strip(),
            sku=data['sku'].strip().upper(),  # Normalize SKU to uppercase
            price=price,
        )
        db.session.add(product)

        # FIX #1: Use flush() to get product.id without committing yet.
        #         Both product and inventory will be committed together below
        #         in a single atomic transaction.
        db.session.flush()

        inventory = Inventory(
            product_id=product.id,
            warehouse_id=data['warehouse_id'],
            quantity=initial_quantity,
        )
        db.session.add(inventory)

        # FIX #1: Single commit — either both records are saved or neither is.
        #         This eliminates the partial-write race condition.
        db.session.commit()

        # FIX #7: Return 201 Created (not 200) for resource creation
        return jsonify({
            "message": "Product created successfully",
            "product_id": product.id
        }), 201

    except IntegrityError as e:
        # FIX #10: Always rollback on exception to keep DB consistent
        db.session.rollback()

        # FIX #3: Handle SKU uniqueness violation gracefully
        if 'sku' in str(e.orig).lower():
            return jsonify({"error": f"SKU '{data['sku']}' already exists"}), 409

        # Handle invalid warehouse_id (FK violation)
        if 'warehouse' in str(e.orig).lower():
            return jsonify({"error": "warehouse_id does not exist"}), 400

        return jsonify({"error": "Database constraint violated"}), 400

    except Exception as e:
        db.session.rollback()
        # FIX #9: Log the full traceback for observability (use Sentry in production)
        logging.exception("Unexpected error while creating product")
        return jsonify({"error": "Internal server error"}), 500
