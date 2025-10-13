class Tag:
    def __init__(self,spaces,parentheses,content,condition,row,idnum):
        self.spaces=spaces  
        self.parentheses=parentheses  
        self.content=content  
        self.condition=condition  
        self.row=row 
        self.idnum=idnum
    def getSpaces(self):
        return self.spaces
    def getParentheses(self):
        return self.parentheses
    def getContent(self):
        return self.content
    def getCondition(self):
        return self.condition
    def getRow(self):
        return self.row
    def getId(self):
        return self.idnum