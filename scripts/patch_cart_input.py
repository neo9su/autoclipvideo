def scheduler(s):
    old='''        err_msg = str(e)
        logger.error(f"Task {task_id} failed: {err_msg}")'''
    new='''        err_msg = str(e)
        from publish_cart_input import needs_cart_input
        if needs_cart_input(e):
            await _set_status("waiting_input", error_msg="等待补充挂车商品：" + err_msg[:400] + "；请打开 /publish-cart-input 修改商品后继续原任务")
            logger.warning("Task %s waiting for cart input: %s", task_id, err_msg)
            return
        logger.error(f"Task {task_id} failed: {err_msg}")'''
    assert s.count(old)==1
    return s.replace(old,new)

def review(s):
    old='router = APIRouter()'
    assert s.count(old)==1
    return s.replace(old,old+'\nfrom publish_cart_input import router as cart_input_router\nrouter.include_router(cart_input_router)')
