from app.http import Router, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.rbac import get_current_user
from app.db.database import get_db
from app.services import todo_service
from app.schemas.todo import TodoCreate, TodoUpdate, TodoPublic, PaginatedTodos

router = Router()


@router.get('/', response_model=PaginatedTodos)
def list_my_todos(page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200), db: Session = Depends(get_db), user=Depends(get_current_user)):
    offset = (page - 1) * size
    items, total = todo_service.list_todos(db, employee_id=user.id, limit=size, offset=offset)
    public = [TodoPublic(
        id=i.id,
        employee_id=i.employee_id,
        title=i.title,
        description=i.description,
        status=i.status,
        due_date=i.due_date,
        created_at=i.created_at.isoformat() if i.created_at else None,
        updated_at=i.updated_at.isoformat() if i.updated_at else None,
    ) for i in items]
    return PaginatedTodos(items=public, total=total, page=page, size=size)


@router.post('/', response_model=TodoPublic)
def create_todo(payload: TodoCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    todo = todo_service.create_todo(db, employee_id=user.id, payload=payload)
    return TodoPublic(
        id=todo.id,
        employee_id=todo.employee_id,
        title=todo.title,
        description=todo.description,
        status=todo.status,
        due_date=todo.due_date,
        created_at=todo.created_at.isoformat() if todo.created_at else None,
        updated_at=todo.updated_at.isoformat() if todo.updated_at else None,
    )


@router.put('/{todo_id}', response_model=TodoPublic)
def update_my_todo(todo_id: str, payload: TodoUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    todo = todo_service.get_todo(db, todo_id)
    if not todo or todo.employee_id != user.id:
        raise HTTPException(status_code=404, detail='Todo not found')
    todo = todo_service.update_todo(db, todo, payload)
    return TodoPublic(
        id=todo.id,
        employee_id=todo.employee_id,
        title=todo.title,
        description=todo.description,
        status=todo.status,
        due_date=todo.due_date,
        created_at=todo.created_at.isoformat() if todo.created_at else None,
        updated_at=todo.updated_at.isoformat() if todo.updated_at else None,
    )


@router.delete('/{todo_id}')
def delete_my_todo(todo_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    todo = todo_service.get_todo(db, todo_id)
    if not todo or todo.employee_id != user.id:
        raise HTTPException(status_code=404, detail='Todo not found')
    todo_service.delete_todo(db, todo)
    return {'ok': True}
