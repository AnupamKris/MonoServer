from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
import dataclasses
import uuid
import time

app = Flask(__name__)
app.config["SECRET_KEY"] = "w470vgq7bp9t8y7 oa59"
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory storage for rooms (in a real application, you'd use a database)
rooms = {}


@dataclass
class Player:
    name: str
    money: int
    joined: bool
    id: str

    def to_dict(self):
        return {k: v for k, v in asdict(self).items()}


@dataclass
class Transaction:
    id: str
    from_player: str
    to_player: str
    from_player_id: str
    to_player_id: str
    amount: int
    timestamp: float


@dataclass
class BankRequest:
    id: str
    player_id: str
    amount: int
    approvals: List[str]
    rejections: List[str]


@dataclass
class RoomData:
    id: str
    started: bool = False
    created: bool = False
    startingMoney: int = 1500
    passGoMoney: int = 200
    players: List[Player] = dataclasses.field(default_factory=list)
    transactions: List[Transaction] = dataclasses.field(default_factory=list)
    bank_requests: Dict[str, BankRequest] = dataclasses.field(default_factory=dict)

    def to_dict(self):
        return {
            **asdict(self),
            "players": [p.to_dict() for p in self.players],
            "transactions": [asdict(t) for t in self.transactions],
            "bank_requests": {k: asdict(v) for k, v in self.bank_requests.items()},
        }


# REST endpoints
@app.route("/create_room", methods=["POST"])
def create_room():
    data = request.get_json()
    room_id = data.get("id")

    if room_id in rooms:
        return jsonify({"error": "Room already exists"}), 400

    rooms[room_id] = RoomData(id=room_id)
    print(rooms[room_id], "ROOM DATA")

    return jsonify({"available": True, "message": "Room is Created"})


@app.route("/check_room/<room_id>", methods=["GET"])
def check_room(room_id):
    if room_id in rooms:
        return jsonify({"available": False, "message": "Room exists"})
    return jsonify({"available": True, "message": "Room is available"})


# Socket.IO event handlers
@socketio.on("join")
def handle_join(data):
    print(data, "DATA")
    room_id = data.get("roomId")
    user_id = data.get("userId")
    if not room_id or room_id not in rooms:
        emit("error", "Invalid room ID")
        return

    join_room(room_id)
    emit("join_success", f"Joined room: {room_id}")
    emit("newRoomData", rooms[room_id].to_dict())
    emit(
        "user_joined",
        f"User {user_id} joined the room",
        to=room_id,
        skip_sid=request.sid,
    )


@socketio.on("leave")
def handle_leave(room_id):
    if not room_id or room_id not in rooms:
        emit("error", "Invalid room ID")
        return

    leave_room(room_id)
    emit("leave_success", f"Left room: {room_id}")
    emit("user_left", f"User {request.sid} left the room", to=room_id)


@socketio.on("message")
def handle_message(data):
    room_id = data.get("room")
    message = data.get("message")

    if not room_id or room_id not in rooms or not message:
        emit("error", "Invalid room ID or message")
        return

    emit("message", {"user": request.sid, "message": message}, to=room_id)


@socketio.on("roomData")
def handle_room_data(data):
    room_id = data.get("room")
    room_data = data.get("data")

    if not room_id or room_id not in rooms or not room_data:
        emit("error", "Invalid room ID or data")
        return

    # Convert the incoming dictionary to RoomData object
    new_room_data = RoomData(
        id=room_data["id"],
        started=room_data["started"],
        created=room_data["created"],
        startingMoney=room_data["startingMoney"],
        passGoMoney=room_data["passGoMoney"],
        creator=room_data["creator"],
        players=[Player(**p) for p in room_data["players"]],
    )

    rooms[room_id] = new_room_data
    emit("roomData", rooms[room_id].to_dict(), to=room_id)


@socketio.on("setRoomData")
def handle_set_room_data(data):
    room_id = data.get("room")
    startingMoney = data.get("startingMoney")
    passGoMoney = data.get("passGoMoney")

    if not room_id or room_id not in rooms:
        emit("error", "Invalid room ID")
        return

    rooms[room_id].startingMoney = startingMoney
    rooms[room_id].passGoMoney = passGoMoney
    rooms[room_id].created = True
    emit("roomData", rooms[room_id].to_dict(), to=room_id)


@socketio.on("joinGame")
def handle_join_game(data):
    room_id = data.get("room")
    player_name = data.get("player_name")
    user_id = data.get("userId")
    print(room_id, player_name, user_id)
    if not room_id or room_id not in rooms or not player_name or not user_id:
        emit("error", "Invalid room ID, player name, or user ID")
        return

    room = rooms[room_id]
    existing_player = next(
        (player for player in room.players if player.id == user_id), None
    )

    if existing_player:
        # Player is rejoining, update their data and return
        existing_player.name = player_name
        existing_player.joined = True
        emit("roomData", room.to_dict(), to=room_id)
        return

    if room.started:
        emit("error", "Game has already started. Cannot join.")
        return

    new_player = Player(
        name=player_name, money=room.startingMoney, joined=True, id=user_id
    )
    room.players.append(new_player)
    emit("roomData", room.to_dict(), to=room_id)


@socketio.on("startGame")
def handle_start_game(room_id):
    if not room_id or room_id not in rooms:
        emit("error", "Invalid room ID")
        return

    room = rooms[room_id]
    if not room.created or room.started:
        print("Cannot start the game", room.created, room.started)
        emit("error", "Cannot start the game")
        return

    room.started = True
    emit("roomData", room.to_dict(), to=room_id)


@socketio.on("pay")
def handle_pay(data):
    room_id = data.get("room")
    amount = data.get("amount")
    to_id = data.get("to")
    from_id = data.get("from")

    if not room_id or room_id not in rooms:
        emit("error", "Invalid room ID")
        return

    room = rooms[room_id]

    # Find players by their IDs
    from_player = next((p for p in room.players if p.id == from_id), None)

    if to_id != "bank":
        to_player = next((p for p in room.players if p.id == to_id), None)
        if not to_player:
            emit("error", "Invalid player IDs")
            return
        # Perform the transaction for non-bank recipient
        to_player.money += int(amount)

    if not from_player:
        emit("error", "Invalid player IDs")
        return

    # Perform the transaction for the paying player
    from_player.money -= int(amount)

    if to_id != "bank":
        emit(
            "paymentRecieved",
            {"from": from_player.name, "to": to_player.name, "amount": amount},
            to=to_id,
        )

    emit(
        "paymentSent",
        {
            "from": from_player.name,
            "to": "Bank" if to_id == "bank" else to_player.name,
            "amount": amount,
        },
        to=from_id,
    )

    # Add transaction to the room's transaction history
    transaction = Transaction(
        id=str(uuid.uuid4()),
        from_player=from_player.name,
        to_player="Bank" if to_id == "bank" else to_player.name,
        from_player_id=from_id,
        to_player_id=to_id,
        amount=int(amount),
        timestamp=time.time(),
    )
    room.transactions.append(transaction)
    emit("roomData", room.to_dict(), to=room_id)


@socketio.on("requestFromBank")
def handle_bank_request(data):
    room_id = data.get("room")
    player_id = data.get("player_id")
    amount = data.get("amount")

    if not room_id or room_id not in rooms:
        emit("error", "Invalid room ID")
        return

    room = rooms[room_id]
    player = next((p for p in room.players if p.id == player_id), None)

    if not player:
        emit("error", "Invalid player ID")
        return

    request_id = str(uuid.uuid4())
    bank_request = BankRequest(
        id=request_id, player_id=player_id, amount=amount, approvals=[], rejections=[]
    )
    room.bank_requests[request_id] = bank_request

    emit("roomData", room.to_dict(), to=room_id)
    emit("newBankRequest", asdict(bank_request), to=room_id)


@socketio.on("respondToBankRequest")
def handle_bank_request_response(data):
    room_id = data.get("room")
    request_id = data.get("request_id")
    player_id = data.get("player_id")
    approved = data.get("approved")

    if not room_id or room_id not in rooms:
        emit("error", "Invalid room ID")
        return

    room = rooms[room_id]
    if request_id not in room.bank_requests:
        emit("error", "Invalid bank request ID")
        return

    bank_request = room.bank_requests[request_id]

    if approved:
        bank_request.approvals.append(player_id)
    else:
        bank_request.rejections.append(player_id)

    if len(bank_request.approvals) >= 2:
        # Process the bank request
        requester = next(
            (p for p in room.players if p.id == bank_request.player_id), None
        )
        if requester:
            requester.money += bank_request.amount
            transaction = Transaction(
                id=str(uuid.uuid4()),
                from_player="Bank",
                to_player=requester.name,
                from_player_id="bank",
                to_player_id=requester.id,
                amount=bank_request.amount,
                timestamp=time.time(),
            )
            room.transactions.append(transaction)
            emit("bankRequestApproved", asdict(bank_request), to=room_id)
        del room.bank_requests[request_id]
    elif len(bank_request.rejections) >= 2:
        # Remove the bank request
        del room.bank_requests[request_id]
        emit("bankRequestRejected", asdict(bank_request), to=room_id)
    else:
        # Update the bank request status
        emit("bankRequestUpdated", asdict(bank_request), to=room_id)

    emit("roomData", room.to_dict(), to=room_id)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, debug=True, allow_unsafe_werkzeug=True)
