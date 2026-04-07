# Original Code – Annotated with Issues
# ============================================================
# This is the original code submitted for review.
# Each issue is marked with a comment explaining the problem.

@app.route('/api/products', methods=['POST'])
def create_product():
    data = request.json  # BUG #8: Use get_json() instead; request.json raises
                         # an exception if Content-Type header is wrong

    # BUG #2: No input validation — any missing field causes an unhandled KeyError (500 crash)
    # BUG #4: warehouse_id does not belong on Product; products exist across many warehouses
    product = Product(
        name=data['name'],
        sku=data['sku'],         # BUG #3: No SKU uniqueness check at app layer
        price=data['price'],     # BUG #5: price not validated (could be negative, a string, etc.)
        warehouse_id=data['warehouse_id']  # BUG #4: wrong field on Product model
    )

    db.session.add(product)
    db.session.commit()  # BUG #1: FIRST commit — if the code crashes after this line,
                         # the product exists in DB but has NO inventory record.
                         # This is a partial-write / race condition bug.

    # BUG #2: 'initial_quantity' not validated — could be missing, negative, or non-integer
    inventory = Inventory(
        product_id=product.id,
        warehouse_id=data['warehouse_id'],
        quantity=data['initial_quantity']
    )
    db.session.add(inventory)
    db.session.commit()  # BUG #1: SECOND commit — should be a single atomic transaction

    # BUG #7: Returns 200 implicitly — should return 201 Created for resource creation
    # BUG #6: No authentication/authorization check
    # BUG #9: No logging — silent failures in production
    # BUG #10: No rollback on exception — DB left in inconsistent state
    return {"message": "Product created", "product_id": product.id}
