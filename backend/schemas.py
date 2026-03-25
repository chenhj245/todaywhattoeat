from typing import Literal, Optional

from pydantic import BaseModel, Field


QuantityDesc = Literal["充足", "一些", "快没了", "少量"]
CategoryName = Literal["蔬菜", "肉类", "蛋奶", "调味品", "主食", "冷冻", "水果", "其他"]
DeleteMode = Literal["exact", "contains", "prefix", "predicate"]
DeletePredicate = Literal["contains_ascii", "contains_digit"]


class IngredientItem(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    quantity_num: Optional[float] = None
    quantity_desc: Optional[QuantityDesc] = None
    unit: Optional[str] = Field(default=None, max_length=10)
    category: Optional[CategoryName] = None


class AddPayload(BaseModel):
    items: list[IngredientItem] = Field(default_factory=list)


class ConsumeItem(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    amount: Optional[float] = None


class ConsumePayload(BaseModel):
    reason: str = Field(min_length=1, max_length=200)
    recipe_names: list[str] = Field(default_factory=list)
    items: list[ConsumeItem] = Field(default_factory=list)


class DeletePayload(BaseModel):
    mode: Optional[DeleteMode] = None
    keyword: Optional[str] = Field(default=None, max_length=30)
    predicate: Optional[DeletePredicate] = None


class QueryPayload(BaseModel):
    min_confidence: float = Field(default=0.1, ge=0.0, le=1.0)


class ShoppingPayload(BaseModel):
    planned_meals: list[str] = Field(default_factory=list)


class SuggestPayload(BaseModel):
    constraints: Optional[str] = Field(default=None, max_length=300)
    max_results: int = Field(default=3, ge=1, le=8)
    exclude_recipes: list[str] = Field(default_factory=list)
    servings: Optional[int] = Field(default=None, ge=1, le=20)
    meal_role: Optional[str] = Field(default=None, max_length=20)


class HowtoPayload(BaseModel):
    recipe_name: str = Field(min_length=1, max_length=30)


class RecipeCheckPayload(BaseModel):
    recipe_name: str = Field(min_length=1, max_length=30)
    focus_ingredients: list[str] = Field(default_factory=list)


class ClarifyPayload(BaseModel):
    message: str = "请补充更明确的操作目标。"
